from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class StudySessionRow(Entity, Base):
    """One 开始学习: what it was for, the actions it sent, and when the user finished it."""

    __tablename__ = "study_session"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_study_session_owner_id_idempotency_key"
        ),
    )

    course_code: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))  # started | finished
    next: Mapped[dict[str, Any]] = mapped_column(JSON)  # NextUp at the time of the start
    # [{"label", "action_run_id" (None when not sent), "message"}]; live status is read
    # from the action runs.
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str] = mapped_column(Text, default="")
