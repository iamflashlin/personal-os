from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity


class EvidenceRow(Entity, Base):
    __tablename__ = "evidence"

    task_id: Mapped[str] = mapped_column(ForeignKey("task.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text)
