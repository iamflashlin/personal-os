from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class JobRow(Entity, Base):
    __tablename__ = "job"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_job_owner_id_key"),)

    kind: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ScheduleRow(Entity, Base):
    __tablename__ = "job_schedule"
    __table_args__ = (UniqueConstraint("owner_id", "kind", name="uq_job_schedule_owner_id_kind"),)

    kind: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    interval_s: Mapped[int] = mapped_column(Integer)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime())
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
