from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class ActionRunRow(Entity, Base):
    """One action sent to an agent. Committed before the frame goes out (ADR 0014)."""

    __tablename__ = "action_run"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_action_run_owner_id_key"),
    )

    name: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(2))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("device.id", ondelete="RESTRICT"))
    message: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
