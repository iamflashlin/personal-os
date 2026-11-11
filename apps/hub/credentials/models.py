from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class CredentialRow(Entity, Base):
    """That a secret exists, and when it was set and used. The secret is in keyring only."""

    __tablename__ = "credential"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_credential_owner_id_name"),)

    name: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(String(200), default="")
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
