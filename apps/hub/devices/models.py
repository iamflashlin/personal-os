from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class DeviceRow(Entity, Base):
    """A paired desktop agent. The token itself is never stored, only its SHA-256."""

    __tablename__ = "device"

    name: Mapped[str] = mapped_column(String(80))
    platform: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_disconnected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PairingCodeRow(Entity, Base):
    """A one-time code shown to the user; only its SHA-256 is stored."""

    __tablename__ = "pairing_code"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    device_id: Mapped[str | None] = mapped_column(ForeignKey("device.id", ondelete="RESTRICT"))
