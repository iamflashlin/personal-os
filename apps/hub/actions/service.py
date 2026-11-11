"""Desktop actions, executed at most once per Idempotency-Key (ADR 0014).

The run row is committed before the request is sent, and the Hub never resends it: a run
whose result never arrives becomes `lost`, and only the user decides to try again.
"""

import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.actions.models import ActionRunRow
from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Forbidden, Invalid, NotFound, Unavailable
from apps.hub.devices import service as devices
from packages.contracts.actions import (
    ACTION_SPECS,
    AUTO_APPROVED_RISKS,
    ActionCreate,
    ActionRequest,
    ActionResult,
    ActionRun,
    ActionRunStatus,
    parse_params,
)

ENTITY = "action_run"
_OPEN = (ActionRunStatus.dispatched, ActionRunStatus.lost)


@dataclass(frozen=True)
class Dispatch:
    run: ActionRun
    request: ActionRequest | None  # None: a replay, nothing is sent


def _read(row: ActionRunRow) -> ActionRun:
    return ActionRun.model_validate(row, from_attributes=True)


def _validated(payload: ActionCreate) -> dict[str, object]:
    spec = ACTION_SPECS[payload.name]
    if spec.risk not in AUTO_APPROVED_RISKS:
        raise Forbidden(f"{payload.name} is {spec.risk} and needs a grant, which S8 adds")
    try:
        return parse_params(payload.name, payload.params).model_dump(mode="json")
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise Invalid(f"invalid params for {payload.name}: {problems}") from exc


def _request_hash(name: str, params: dict[str, object]) -> str:
    canonical = json.dumps({"name": name, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def begin(
    session: Session,
    actor: Actor,
    idempotency_key: str,
    payload: ActionCreate,
    link: devices.AgentLink | None,
) -> Dispatch:
    """Store a new run for `link`'s agent, or return the run this key already made."""

    def op() -> audit.Outcome[Dispatch]:
        # Inside op(), so a refused risk level or invalid params is audited too.
        params = _validated(payload)
        request_hash = _request_hash(payload.name, params)
        spec = ACTION_SPECS[payload.name]
        seen = session.scalars(
            select(ActionRunRow).where(
                ActionRunRow.owner_id == actor.owner_id,
                ActionRunRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if seen is not None:
            if seen.request_hash != request_hash:
                raise Invalid("Idempotency-Key was already used with a different body")
            return audit.Outcome(seen.id, Dispatch(_read(seen), None), result="replayed")
        if link is None:
            # No row is written, so the same key works once the agent is back (D2).
            raise Unavailable("agent offline")
        if payload.name not in link.supported_actions:
            raise Conflict(f"the connected agent does not support {payload.name}")
        row = ActionRunRow(
            owner_id=actor.owner_id,
            source=actor.source,
            name=payload.name,
            params=params,
            request_hash=request_hash,
            risk_level=spec.risk,
            idempotency_key=idempotency_key,
            status=ActionRunStatus.dispatched,
            device_id=link.device_id,
            message="",
            evidence=[],
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict("Idempotency-Key is being used by a concurrent request") from exc
        request = ActionRequest(
            action_id=row.id,
            idempotency_key=idempotency_key,
            name=payload.name,
            params=params,
            risk_level=spec.risk,
            timeout_s=spec.timeout_s,
            issued_at=row.created_at,
        )
        return audit.Outcome(row.id, Dispatch(_read(row), request), {"device_id": link.device_id})

    detail = {
        "name": payload.name,
        "params": payload.params,
        "idempotency_key": idempotency_key,
    }
    return audit.audited(session, actor, ENTITY, "dispatch", None, detail, op)


def record_result(session: Session, actor: Actor, result: ActionResult) -> None:
    """Store what the agent reported. A result for a run this device was not sent is
    refused and audited, never raised, so one bad frame does not drop the connection."""

    def op() -> audit.Outcome[None]:
        row = session.get(ActionRunRow, result.action_id)
        if (
            row is None
            or row.owner_id != actor.owner_id
            or row.device_id != actor.device_id
            or row.idempotency_key != result.idempotency_key
        ):
            return audit.Outcome(result.action_id, None, {"reason": "unknown run"}, "rejected")
        if row.status not in _OPEN:
            return audit.Outcome(row.id, None, {"reason": f"already {row.status}"}, "unchanged")
        # A late result for a `lost` run is still the truth about what happened.
        row.status = ActionRunStatus(result.status.value)
        row.message = audit.redact_text(result.message)
        # Window titles and notes can carry URLs with tokens in them.
        row.evidence = audit.redact([e.model_dump(mode="json") for e in result.evidence])
        row.finished_at = result.finished_at
        session.flush()
        return audit.Outcome(row.id, None, {"evidence_items": len(result.evidence)})

    detail = {"status": result.status, "replayed": result.replayed}
    audit.audited(session, actor, ENTITY, "result", result.action_id, detail, op)


def mark_lost(session: Session, actor: Actor, action_ids: set[str]) -> None:
    """Runs that were sent but never answered; each becomes `lost` with its own audit.

    A run that is gone or already settled is skipped: nothing changes, so nothing is logged.
    """
    for action_id in sorted(action_ids):
        row = session.get(ActionRunRow, action_id)
        if (
            row is None
            or row.owner_id != actor.owner_id
            or row.status != ActionRunStatus.dispatched
        ):
            continue

        def op(row: ActionRunRow = row) -> audit.Outcome[None]:
            row.status = ActionRunStatus.lost
            row.message = "the agent disconnected before reporting a result"
            session.flush()
            return audit.Outcome(row.id, None)

        audit.audited(session, actor, ENTITY, "lost", action_id, {}, op)


def mark_orphans_lost(session: Session, actor: Actor) -> None:
    """At startup no agent is connected, so every run still `dispatched` is lost."""
    ids = session.scalars(
        select(ActionRunRow.id).where(
            ActionRunRow.owner_id == actor.owner_id,
            ActionRunRow.status == ActionRunStatus.dispatched,
        )
    ).all()
    mark_lost(session, actor, set(ids))


def get(session: Session, actor: Actor, action_id: str) -> ActionRun:
    row = session.get(ActionRunRow, action_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"action run {action_id} not found")
    return _read(row)


def list_runs(session: Session, actor: Actor, limit: int) -> list[ActionRun]:
    rows = session.scalars(
        select(ActionRunRow)
        .where(ActionRunRow.owner_id == actor.owner_id)
        .order_by(ActionRunRow.created_at.desc(), ActionRunRow.id.desc())
        .limit(limit)
    ).all()
    return [_read(r) for r in rows]
