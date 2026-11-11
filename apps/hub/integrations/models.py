from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class IntegrationRow(Entity, Base):
    """An outside source. Its secret (token, password, private feed URL) is a credential."""

    __tablename__ = "integration"

    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    credential_name: Mapped[str] = mapped_column(String(80))
    interval_s: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str] = mapped_column(Text, default="")
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SyncedItemRow(Entity, Base):
    """One thing a source returned, recognised on the next sync by its external id."""

    __tablename__ = "synced_item"
    __table_args__ = (
        UniqueConstraint(
            "integration_id", "item_type", "external_id", name="uq_synced_item_source_id"
        ),
    )

    integration_id: Mapped[str] = mapped_column(
        ForeignKey("integration.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
