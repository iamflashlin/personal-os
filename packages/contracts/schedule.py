"""The schedule (ADR 0038): the user's own events (classes, activities, workouts, task
blocks), merged with synced calendar events and Canvas deadlines into one agenda."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventKind = Literal["class", "activity", "workout", "task", "exam", "other"]
Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MAX_SPAN_DAYS = 62


class EventFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=200)]
    kind: EventKind = "other"
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    location: Annotated[str, Field(max_length=300)] = ""
    notes: Annotated[str, Field(max_length=2000)] = ""
    repeat_days: list[Weekday] = []  # weekly on these days (local time of starts_at)
    repeat_until: date | None = None

    @model_validator(mode="after")
    def _order(self) -> "EventFields":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("times must carry a time zone offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("an event must end after it starts")
        if (self.ends_at - self.starts_at).days > 14:
            raise ValueError("one occurrence may last at most 14 days")
        if self.repeat_until is not None and not self.repeat_days:
            raise ValueError("repeat_until needs repeat_days")
        return self


class NewEvent(EventFields):
    pass


class EventPatch(BaseModel):
    """Replace an event's fields; `version` guards against overwriting a newer edit."""

    model_config = ConfigDict(extra="forbid")
    fields: EventFields
    version: int


class ScheduleEvent(EventFields):
    model_config = ConfigDict(extra="ignore")
    id: str
    source: str  # manual | ai (later)
    created_at: datetime
    updated_at: datetime
    version: int


class AgendaEntry(BaseModel):
    """One thing in the agenda. `blocks` = it takes up time (used for conflicts and free
    time); a Canvas deadline is a point in time and does not block."""

    key: str  # unique in the agenda: source, id and occurrence date
    title: str
    kind: str  # an EventKind, or "deadline" / "calendar"
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    location: str
    source: Literal["manual", "calendar", "canvas"]
    event_id: str | None  # the editable event behind a manual entry
    url: str
    blocks: bool
    conflict: bool = False


class FreeSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    minutes: int


class Agenda(BaseModel):
    start: datetime
    end: datetime
    time_zone: str
    entries: list[AgendaEntry]
    free: list[FreeSlot]  # within the day window, not blocked by any entry
    day_window: tuple[int, int]  # local hours considered for free time, e.g. (8, 22)
