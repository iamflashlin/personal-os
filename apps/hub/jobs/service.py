"""Background jobs: a SQLite queue, retries with backoff, interval schedules (ADR 0017).

At least once: a job interrupted by a crash is queued again at startup, so handlers must
be idempotent. One in-process worker (`worker.JobWorker`) runs them.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.jobs.models import JobRow, ScheduleRow
from packages.contracts.jobs import Job, JobStatus, Schedule

logger = logging.getLogger(__name__)

ENTITY = "job"
DEFAULT_MAX_ATTEMPTS = 5
MAX_BACKOFF = timedelta(hours=1)
MAX_ERROR = 2000

Handler = Callable[[Engine, Job], None]


class JobKinds:
    """kind -> handler. Modules contribute handlers through `main`, never by import."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._families: dict[str, Handler] = {}

    def register(self, kind: str, handler: Handler) -> None:
        if kind in self._handlers or kind in self._families:
            raise ValueError(f"job kind {kind} is already registered")
        self._handlers[kind] = handler

    def register_family(self, family: str, handler: Handler) -> None:
        """Handle `family` and every `family:<anything>` (one schedule per integration).
        Only registered families route this way; another kind with a colon has no handler."""
        if family in self._handlers or family in self._families:
            raise ValueError(f"job kind {family} is already registered")
        self._families[family] = handler

    def get(self, kind: str) -> Handler | None:
        if kind in self._handlers:
            return self._handlers[kind]
        return self._families.get(kind.partition(":")[0])


def _read(row: JobRow) -> Job:
    return Job.model_validate(row, from_attributes=True)


def _read_schedule(row: ScheduleRow) -> Schedule:
    return Schedule.model_validate(row, from_attributes=True)


def _hash(kind: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _get_row(session: Session, actor: Actor, job_id: str) -> JobRow:
    row = session.get(JobRow, job_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"job {job_id} not found")
    return row


def _new_job(
    session: Session,
    actor: Actor,
    kind: str,
    payload: dict[str, Any],
    *,
    run_at: datetime,
    idempotency_key: str | None,
    max_attempts: int,
) -> tuple[JobRow, bool]:
    """The job for this key: (row, created). Raises Invalid if the key's job differs."""
    payload_hash = _hash(kind, payload)
    if idempotency_key is not None:
        seen = session.scalars(
            select(JobRow).where(
                JobRow.owner_id == actor.owner_id, JobRow.idempotency_key == idempotency_key
            )
        ).one_or_none()
        if seen is not None:
            if seen.payload_hash != payload_hash:
                raise Invalid(f"job key {idempotency_key} was already used for different work")
            return seen, False
    row = JobRow(
        owner_id=actor.owner_id,
        source=actor.source,
        kind=kind,
        payload=payload,
        payload_hash=payload_hash,
        status=JobStatus.queued,
        attempts=0,
        max_attempts=max_attempts,
        run_at=run_at,
        idempotency_key=idempotency_key,
        last_error="",
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise Conflict(f"job key {idempotency_key} is being used concurrently") from exc
    return row, True


def enqueue(
    session: Session,
    actor: Actor,
    kind: str,
    payload: dict[str, Any],
    *,
    now: datetime,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Job:
    if max_attempts < 1:
        raise Invalid("max_attempts must be at least 1")

    def op() -> audit.Outcome[Job]:
        row, created = _new_job(
            session,
            actor,
            kind,
            payload,
            run_at=run_at or now,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )
        return audit.Outcome(row.id, _read(row), result="ok" if created else "replayed")

    detail = {"kind": kind, "payload": payload, "idempotency_key": idempotency_key}
    return audit.audited(session, actor, ENTITY, "enqueue", None, detail, op)


def claim_next(session: Session, actor: Actor, now: datetime) -> Job | None:
    """Mark the earliest due job running and count the attempt; None if nothing is due."""
    row = session.scalars(
        select(JobRow)
        .where(
            JobRow.owner_id == actor.owner_id,
            JobRow.status == JobStatus.queued,
            JobRow.run_at <= now,
        )
        .order_by(JobRow.run_at, JobRow.id)
        .limit(1)
    ).one_or_none()
    if row is None:
        return None

    # Read outside the audited op; a stale write still fails on the version column there.
    def op() -> audit.Outcome[Job]:
        row.status = JobStatus.running
        row.attempts += 1
        row.started_at = now
        row.finished_at = None
        session.flush()
        return audit.Outcome(row.id, _read(row), {"attempt": row.attempts})

    return audit.audited(session, actor, ENTITY, "start", row.id, {"kind": row.kind}, op)


def backoff(attempts: int, base: timedelta) -> timedelta:
    """Delay before the next attempt: base, 2·base, 4·base, … capped at one hour."""
    return min(base * 2 ** max(attempts - 1, 0), MAX_BACKOFF)


def finish(
    session: Session,
    actor: Actor,
    job_id: str,
    *,
    now: datetime,
    error: str | None = None,
    permanent: bool = False,
    retry_base: timedelta = timedelta(seconds=5),
) -> Job:
    """Record an attempt's outcome: succeeded, queued again after a delay, or dead."""

    def op() -> audit.Outcome[Job]:
        row = _get_row(session, actor, job_id)
        if row.status != JobStatus.running:
            raise Conflict(f"job {job_id} is {row.status}, not running")
        row.finished_at = now
        if error is None:
            row.status = JobStatus.succeeded
            row.last_error = ""
            result = "succeeded"
        else:
            row.last_error = audit.redact_text(error)[:MAX_ERROR]
            if permanent or row.attempts >= row.max_attempts:
                row.status = JobStatus.dead
                result = "dead"
            else:
                row.status = JobStatus.queued
                row.run_at = now + backoff(row.attempts, retry_base)
                result = "retry"
        session.flush()
        return audit.Outcome(row.id, _read(row), {"attempt": row.attempts}, result)

    detail = {} if error is None else {"error": error[:MAX_ERROR]}
    return audit.audited(session, actor, ENTITY, "finish", job_id, detail, op)


def requeue_interrupted(
    session: Session,
    actor: Actor,
    now: datetime,
    retry_base: timedelta = timedelta(seconds=5),
    reason: str = "interrupted by a Hub restart",
) -> int:
    """Recover jobs left `running` when nothing is running them: at startup, or at the
    start of a worker pass (the one worker runs jobs one at a time). The cut-off attempt
    counts, so a job that keeps killing the Hub ends up `dead` instead of looping."""
    ids = session.scalars(
        select(JobRow.id).where(
            JobRow.owner_id == actor.owner_id, JobRow.status == JobStatus.running
        )
    ).all()
    for job_id in ids:

        def op(job_id: str = job_id) -> audit.Outcome[None]:
            row = _get_row(session, actor, job_id)
            row.last_error = reason
            row.finished_at = now
            if row.attempts >= row.max_attempts:
                row.status = JobStatus.dead
                result = "dead"
            else:
                row.status = JobStatus.queued
                row.run_at = now + backoff(row.attempts, retry_base)
                result = "ok"
            session.flush()
            return audit.Outcome(row.id, None, {"attempt": row.attempts}, result)

        audit.audited(session, actor, ENTITY, "requeue", job_id, {}, op)
    return len(ids)


def retry(session: Session, actor: Actor, job_id: str, now: datetime) -> Job:
    """A person's decision to try a dead job again, with a fresh set of attempts."""

    def op() -> audit.Outcome[Job]:
        row = _get_row(session, actor, job_id)
        if row.status != JobStatus.dead:
            raise Conflict(f"only a dead job can be retried; this one is {row.status}")
        row.status = JobStatus.queued
        row.attempts = 0
        row.run_at = now
        row.finished_at = None
        session.flush()
        return audit.Outcome(row.id, _read(row))

    return audit.audited(session, actor, ENTITY, "retry", job_id, {}, op)


def get(session: Session, actor: Actor, job_id: str) -> Job:
    return _read(_get_row(session, actor, job_id))


def list_jobs(
    session: Session, actor: Actor, status: JobStatus | None = None, limit: int = 50
) -> list[Job]:
    query = select(JobRow).where(JobRow.owner_id == actor.owner_id)
    if status is not None:
        query = query.where(JobRow.status == status)
    rows = session.scalars(query.order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(limit))
    return [_read(r) for r in rows]


def ensure_schedule(
    session: Session,
    actor: Actor,
    kind: str,
    interval_s: int,
    payload: dict[str, Any],
    *,
    now: datetime,
) -> Schedule:
    """Create or update the owner's schedule for `kind`. Asking for what already exists
    writes nothing, so callers may run this on every start."""
    if interval_s < 1:
        raise Invalid("interval_s must be at least 1")
    row = session.scalars(
        select(ScheduleRow).where(ScheduleRow.owner_id == actor.owner_id, ScheduleRow.kind == kind)
    ).one_or_none()
    if row is not None and row.interval_s == interval_s and row.payload == payload and row.enabled:
        return _read_schedule(row)

    def op() -> audit.Outcome[Schedule]:
        nonlocal row
        if row is None:
            row = ScheduleRow(
                owner_id=actor.owner_id,
                source=actor.source,
                kind=kind,
                payload=payload,
                interval_s=interval_s,
                next_run_at=now,
                enabled=True,
            )
            session.add(row)
        else:
            # A shorter interval takes effect now, not after the old, longer wait.
            row.next_run_at = min(row.next_run_at, now + timedelta(seconds=interval_s))
            row.interval_s = interval_s
            row.payload = payload
            row.enabled = True
        session.flush()
        return audit.Outcome(row.id, _read_schedule(row))

    detail = {"kind": kind, "interval_s": interval_s, "payload": payload}
    return audit.audited(session, actor, "job_schedule", "ensure", None, detail, op)


def fire_due_schedules(session: Session, actor: Actor, now: datetime) -> list[Job]:
    """Enqueue one job per due schedule. Slots missed while the Hub was down collapse
    into this one run; the job key names the slot, so a slot is never enqueued twice."""
    due = session.scalars(
        select(ScheduleRow).where(
            ScheduleRow.owner_id == actor.owner_id,
            ScheduleRow.enabled.is_(True),
            ScheduleRow.next_run_at <= now,
        )
    ).all()
    jobs: list[Job] = []
    for schedule in due:
        # Scheduled jobs are recorded by this `job_schedule.fire` event (with the job id),
        # not by a separate `job.enqueue` event.

        def op(schedule: ScheduleRow = schedule) -> audit.Outcome[Job]:
            slot = schedule.next_run_at
            row, created = _new_job(
                session,
                actor,
                schedule.kind,
                schedule.payload,
                run_at=now,
                idempotency_key=f"schedule:{schedule.kind}:{slot.isoformat()}",
                max_attempts=DEFAULT_MAX_ATTEMPTS,
            )
            step = timedelta(seconds=schedule.interval_s)
            following = slot + step
            schedule.next_run_at = following if following > now else now + step
            session.flush()
            extra = {"job_id": row.id, "slot": slot.isoformat(), "new_job": created}
            return audit.Outcome(schedule.id, _read(row), extra)

        try:
            jobs.append(audit.audited(session, actor, "job_schedule", "fire", schedule.id, {}, op))
        except Exception:
            # Already audited and rolled back; one bad schedule must not stop the others.
            logger.exception("schedule %s (%s) could not fire", schedule.id, schedule.kind)
    return jobs


def delete_schedule(session: Session, actor: Actor, kind: str) -> None:
    """Stop a schedule. Jobs it already queued still run; deleting nothing is fine."""
    row = session.scalars(
        select(ScheduleRow).where(ScheduleRow.owner_id == actor.owner_id, ScheduleRow.kind == kind)
    ).one_or_none()
    if row is None:
        return

    def op() -> audit.Outcome[None]:
        session.delete(row)
        session.flush()
        return audit.Outcome(row.id, None)

    audit.audited(session, actor, "job_schedule", "delete", row.id, {"kind": kind}, op)


def list_schedules(session: Session, actor: Actor) -> list[Schedule]:
    rows = session.scalars(
        select(ScheduleRow).where(ScheduleRow.owner_id == actor.owner_id).order_by(ScheduleRow.kind)
    )
    return [_read_schedule(r) for r in rows]
