from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class CourseProfileRow(Entity, Base):
    """What one course's syllabus says (ADR 0040); one row per owner and course code."""

    __tablename__ = "course_profile"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_course_profile_owner_id_code"),)

    code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200), default="")
    term: Mapped[str] = mapped_column(String(40), default="")
    units: Mapped[float | None] = mapped_column(Float)
    units_source: Mapped[str] = mapped_column(String(300), default="")
    scale: Mapped[list[Any]] = mapped_column(JSON, default=list)
    scale_source: Mapped[str] = mapped_column(String(300), default="")
    categories: Mapped[list[Any]] = mapped_column(JSON, default=list)
    rules: Mapped[list[Any]] = mapped_column(JSON, default=list)
    open_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    syllabus_source: Mapped[str] = mapped_column(String(300), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
