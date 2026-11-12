from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class TriageBatchRow(Entity, Base):
    """One click that marked mails 已处理; undo restores each mail's previous state."""

    __tablename__ = "triage_batch"
    __table_args__ = (Index("ix_triage_batch_owner_status", "owner_id", "status"),)

    kind: Mapped[str] = mapped_column(String(16))  # group | manual
    status: Mapped[str] = mapped_column(String(12))  # applied | undone
    label: Mapped[str] = mapped_column(String(80))  # written by the server
    group_key: Mapped[str] = mapped_column(String(120), default="")
    applied_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_id: Mapped[str | None] = mapped_column(String(26))
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MailTriageStateRow(Entity, Base):
    """An explicit 已处理 / 未处理 mark on one mail; it wins over any rule."""

    __tablename__ = "mail_triage_state"
    __table_args__ = (
        UniqueConstraint("owner_id", "item_id", name="uq_mail_triage_state_owner_id_item_id"),
    )

    item_id: Mapped[str] = mapped_column(
        ForeignKey("synced_item.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(12))  # handled | unhandled | none
    prev_state: Mapped[str] = mapped_column(String(12), default="none")
    batch_id: Mapped[str | None] = mapped_column(String(26), index=True)


class TriageRuleRow(Entity, Base):
    """「以后也这样」: matching mail counts as 已处理. Rules are switched off, never deleted."""

    __tablename__ = "triage_rule"

    name: Mapped[str] = mapped_column(String(80))
    selector: Mapped[dict[str, Any]] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(16), default="mark_handled")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    from_batch_id: Mapped[str | None] = mapped_column(String(26))
