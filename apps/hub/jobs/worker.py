"""The one in-process job worker (ADR 0017). It lives as long as the Hub process."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor
from apps.hub.core.http import run_in_session
from apps.hub.jobs import service
from packages.contracts.jobs import Job

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobWorker:
    def __init__(
        self,
        engine: Engine,
        owner_id: str,
        kinds: service.JobKinds,
        *,
        poll_s: float = 1.0,
        retry_base: timedelta = timedelta(seconds=5),
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._engine = engine
        self._actor = Actor(owner_id=owner_id, source="jobs")
        self._kinds = kinds
        self._poll_s = poll_s
        self._retry_base = retry_base
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def tick(self) -> int:
        """One pass: fire due schedules, then run every due job. Returns jobs run."""
        actor, base = self._actor, self._retry_base
        now = self._clock()
        # Jobs run one at a time and each is finished before the next, so a job still
        # `running` here was left by a `finish` that failed: recover it now, not at the
        # next restart.
        await run_in_session(
            self._engine,
            lambda s: service.requeue_interrupted(
                s, actor, now, base, "the worker could not record how this attempt ended"
            ),
        )
        await run_in_session(self._engine, lambda s: service.fire_due_schedules(s, actor, now))
        ran = 0
        while True:
            due = self._clock()
            job = await run_in_session(
                self._engine, lambda s, due=due: service.claim_next(s, actor, due)
            )
            if job is None:
                return ran
            await self._run(job)
            ran += 1

    async def _run(self, job: Job) -> None:
        handler = self._kinds.get(job.kind)
        error: str | None = None
        permanent = False
        if handler is None:
            error, permanent = f"no handler for job kind {job.kind}", True
        else:
            try:
                await asyncio.to_thread(handler, self._engine, job)
            except Exception as exc:
                # Redacted here, once: handler errors can carry URLs or headers with secrets.
                error = audit.redact_text(f"{type(exc).__name__}: {exc}")
        if error is not None:
            logger.warning("job %s (%s) failed: %s", job.id, job.kind, error)
        actor, now, base = self._actor, self._clock(), self._retry_base
        await run_in_session(
            self._engine,
            lambda s: service.finish(
                s, actor, job.id, now=now, error=error, permanent=permanent, retry_base=base
            ),
        )

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                # One bad pass (e.g. a locked database) must not stop background work.
                logger.exception("job worker pass failed")
            await asyncio.sleep(self._poll_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="job-worker")

    async def stop(self) -> None:
        """Cancel the loop at once. A handler still running in its thread cannot be
        stopped: its job stays `running` and is queued again at the next start (at least
        once), and Python waits for that thread before the process exits (ADR 0017)."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
