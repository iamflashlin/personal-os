from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity


class GoalRow(Entity, Base):
    __tablename__ = "goal"

    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    due_date: Mapped[date | None] = mapped_column(Date)


class ProjectRow(Entity, Base):
    __tablename__ = "project"

    goal_id: Mapped[str | None] = mapped_column(
        ForeignKey("goal.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    due_date: Mapped[date | None] = mapped_column(Date)


class TaskRow(Entity, Base):
    __tablename__ = "task"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("project.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    due_date: Mapped[date | None] = mapped_column(Date)
    execution_mode: Mapped[str] = mapped_column(String(16))
    tags: Mapped[list[str]] = mapped_column(JSON)
    depends_on: Mapped[list[str]] = mapped_column(JSON)


class WorkspaceRow(Entity, Base):
    __tablename__ = "workspace"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("project.id", ondelete="RESTRICT"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("task.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    urls: Mapped[list[str]] = mapped_column(JSON)
    folders: Mapped[list[str]] = mapped_column(JSON)
    apps: Mapped[list[str]] = mapped_column(JSON)


class IdempotencyKeyRow(Entity, Base):
    """Maps a client `Idempotency-Key` to the resource its first POST created."""

    __tablename__ = "idempotency_key"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_idempotency_key_owner_id_key"),)

    key: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(26))
