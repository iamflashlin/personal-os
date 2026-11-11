from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class EmailSummaryRow(Entity, Base):
    """One AI summary of one synced email. Deleted with the mail (FK cascade)."""

    __tablename__ = "email_summary"
    __table_args__ = (
        UniqueConstraint("owner_id", "item_id", name="uq_email_summary_owner_id_item_id"),
    )

    # Indexed so the cascade from a deleted mail finds its summary without a table scan.
    item_id: Mapped[str] = mapped_column(
        ForeignKey("synced_item.id", ondelete="CASCADE"), index=True
    )
    item_hash: Mapped[str] = mapped_column(String(64))  # sender + subject + body
    status: Mapped[str] = mapped_column(String(24), index=True)
    gist: Mapped[str] = mapped_column(Text, default="")
    action_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    action: Mapped[str] = mapped_column(Text, default="")
    deadline_text: Mapped[str] = mapped_column(String(100), default="")
    deadline_date: Mapped[date | None] = mapped_column(Date)
    importance: Mapped[str] = mapped_column(String(8), default="normal")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str] = mapped_column(Text, default="")
    model_call_id: Mapped[str | None] = mapped_column(String(26))
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[int] = mapped_column(Integer, default=0)
