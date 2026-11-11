import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from apps.hub.audit.models import AuditEventRow
from apps.hub.core.domain import Actor, Conflict, DomainError

REDACTED = "[REDACTED]"

_SECRET_NAME = (
    r"(?:token|secret|passw(?:or)?d|pwd|api[_-]?key|authorization|cookie|credential"
    r"|private[_-]?key)"
)
_SENSITIVE_KEY = re.compile(_SECRET_NAME, re.IGNORECASE)


def _requote(value: str) -> str:
    """Replace a secret value, keeping its surrounding quotes if it had them."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return f"{value[0]}{REDACTED}{value[0]}"
    return REDACTED


_SUBSTITUTIONS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), f"://{REDACTED}@"),
    (re.compile(r"(?i)\b(bearer|token|digest)\s+[A-Za-z0-9._~+/=-]{4,}"), rf"\1 {REDACTED}"),
    (re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{8,}"), rf"\1 {REDACTED}"),
    (
        re.compile(
            rf"(?i)(?<![A-Za-z0-9])([\w-]*{_SECRET_NAME})([\"']?\s*[=:]\s*)"
            r"(\"[^\"]*\"|'[^']*'|(?!\[REDACTED\])(?:(?:bearer|basic|token|digest)\s+)?"
            r"[^\s&\"',;]+)"
        ),
        lambda m: f"{m[1]}{m[2]}{_requote(m[3])}",
    ),
    (
        re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b"),
        REDACTED,
    ),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any) -> Any:
    """Return a copy with secret-looking keys and substrings replaced by `[REDACTED]`."""
    if isinstance(value, dict):
        return {
            str(k): REDACTED if _SENSITIVE_KEY.search(str(k)) else redact(v)
            for k, v in value.items()  # pyright: ignore[reportUnknownVariableType]
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str):
        return redact_text(value)
    return value


class AuditEvent(BaseModel):
    id: str
    created_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    result: str
    detail: dict[str, Any]


def record(
    session: Session,
    *,
    owner_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    result: str,
    detail: dict[str, Any],
) -> None:
    """Add one event to `session`; the caller commits it with the change it describes."""
    session.add(
        AuditEventRow(
            owner_id=owner_id,
            source="hub",
            actor=redact_text(actor),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            result=result,
            detail=redact(detail),
        )
    )


def list_events(session: Session, owner_id: str, entity_id: str | None = None) -> list[AuditEvent]:
    query = select(AuditEventRow).where(AuditEventRow.owner_id == owner_id)
    if entity_id is not None:
        query = query.where(AuditEventRow.entity_id == entity_id)
    rows = session.scalars(query.order_by(AuditEventRow.created_at, AuditEventRow.id)).all()
    return [AuditEvent.model_validate(r, from_attributes=True) for r in rows]


@dataclass(frozen=True)
class Outcome[T]:
    """What a write produced: the entity it touched, the value to return, extra detail."""

    entity_id: str | None
    value: T
    detail: dict[str, Any] = field(default_factory=dict[str, Any])
    result: str = "ok"


def audited[T](
    session: Session,
    actor: Actor,
    entity_type: str,
    action: str,
    entity_id: str | None,
    detail: dict[str, Any],
    op: Callable[[], Outcome[T]],
) -> T:
    """Run one write and record exactly one audit event for it.

    On success the event commits in the same transaction as the change. A refused or
    failed write is rolled back first, then audited on its own with the reason.
    """

    def log(result: str, logged_id: str | None, extra: dict[str, Any]) -> None:
        record(
            session,
            owner_id=actor.owner_id,
            actor=actor.name,
            action=f"{entity_type}.{action}",
            entity_type=entity_type,
            entity_id=logged_id,
            result=result,
            detail={**detail, **extra},
        )

    def log_alone(result: str, error: str) -> None:
        # The change is already rolled back; if this audit write also fails, the caller
        # still sees the original error rather than this one.
        session.rollback()
        try:
            log(result, entity_id, {"error": error})
            session.commit()
        except Exception:
            session.rollback()

    try:
        outcome = op()
        log(outcome.result, outcome.entity_id, outcome.detail)
        session.commit()
    except DomainError as exc:
        log_alone(exc.result, str(exc))
        raise
    except (OperationalError, StaleDataError) as exc:
        # WAL: a transaction whose snapshot went stale gets SQLITE_BUSY_SNAPSHOT on write.
        log_alone(Conflict.result, type(exc).__name__)
        raise Conflict(f"{entity_type} was changed concurrently; retry") from exc
    except Exception as exc:
        log_alone("error", type(exc).__name__)
        raise
    return outcome.value
