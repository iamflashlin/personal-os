from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.hub.evidence.models import EvidenceRow
from packages.contracts.evidence import Evidence, EvidenceKind


def _read(row: EvidenceRow) -> Evidence:
    return Evidence.model_validate(row, from_attributes=True)


def record_user_confirmation(
    session: Session, *, owner_id: str, source: str, task_id: str, note: str
) -> Evidence:
    """Add a confirmation to `session`; the caller commits it with the status change."""
    row = EvidenceRow(
        owner_id=owner_id,
        source=source,
        task_id=task_id,
        kind=EvidenceKind.user_confirmation,
        note=note,
    )
    session.add(row)
    session.flush()
    return _read(row)


def list_for_task(session: Session, owner_id: str, task_id: str) -> list[Evidence]:
    rows = session.scalars(
        select(EvidenceRow)
        .where(EvidenceRow.owner_id == owner_id, EvidenceRow.task_id == task_id)
        .order_by(EvidenceRow.created_at, EvidenceRow.id)
    ).all()
    return [_read(r) for r in rows]
