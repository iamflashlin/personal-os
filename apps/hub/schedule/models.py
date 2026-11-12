from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity, UTCDateTime


class ScheduleEventRow(Entity, Base):
    """One of the user's own events; weekly repeats are expanded when the agenda is read."""

    __tablename__ = "schedule_event"

    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # The zone the event was entered in: weekly repeats keep its local wall-clock time.
    time_zone: Mapped[str] = mapped_column(String(64), default="")
    repeat_days: Mapped[list[Any]] = mapped_column(JSON, default=list)
    repeat_until: Mapped[date | None] = mapped_column(Date)
