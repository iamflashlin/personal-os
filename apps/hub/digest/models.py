from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class DigestItemRow(Entity, Base):
    """One piece of outside information for the 简报; `raw_text` keeps the original."""

    __tablename__ = "digest_item"
    __table_args__ = (
        UniqueConstraint("owner_id", "dedup_key", name="uq_digest_item_owner_id_dedup_key"),
    )

    channel: Mapped[str] = mapped_column(String(16), index=True)
    source_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2000), default="")
    topics: Mapped[list[Any]] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    happens_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    important: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dedup_key: Mapped[str] = mapped_column(String(64))  # source + url or title: one item once
