from datetime import datetime

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class MemoryRow(Entity, Base):
    """One remembered thing. `memory_fts` (migration 0004) indexes `body` via triggers."""

    __tablename__ = "memory"

    kind: Mapped[str] = mapped_column(String(16), index=True)
    body: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    sensitivity: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    source_ref: Mapped[str] = mapped_column(Text)
