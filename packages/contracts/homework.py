"""作业 (ADR 0044): each Canvas assignment's submission state, computed from synced items."""

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from packages.contracts.actions import ActionRun

HomeworkState = Literal["missing", "soon", "week", "submitted"]


class PlannedTime(BaseModel):
    """A time block on the schedule for one homework, read back from the schedule."""

    event_id: str
    starts_at: datetime
    ends_at: datetime


class HomeworkItem(BaseModel):
    id: str  # the synced item id
    title: str
    course: str  # Canvas's course name, e.g. "F26 ENGL C1000 Academic Reading..."
    course_code: str
    due_at: datetime | None
    url: str  # the assignment's Canvas page
    points: float | None
    state: HomeworkState
    submitted_at: datetime | None  # when Canvas recorded the submission
    late: bool  # Canvas marked the submission late
    planned: PlannedTime | None = None  # the schedule block set aside for it (T-0067)


class HomeworkSlot(BaseModel):
    """The suggested time to do a homework: the earliest free slot before it is due."""

    starts_at: datetime | None
    ends_at: datetime | None
    reason: str  # why there is none, in plain words; "" when there is one


class HomeworkPlan(BaseModel):
    """The block to set aside, usually the suggested slot (the user may have moved it)."""

    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _order(self) -> "HomeworkPlan":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("times must carry a time zone offset")
        if not timedelta(minutes=10) <= self.ends_at - self.starts_at <= timedelta(hours=8):
            raise ValueError("a homework block lasts 10 minutes to 8 hours")
        return self


class HomeworkBoard(BaseModel):
    generated_at: datetime
    canvas: bool  # a Canvas integration exists
    synced_at: datetime | None  # the newest successful Canvas sync
    reminder: HomeworkItem | None  # the nearest unsubmitted item due within 24 h
    missing: list[HomeworkItem]  # Canvas marks it missing
    soon: list[HomeworkItem]  # not submitted, due within 24 h
    week: list[HomeworkItem]  # not submitted, due within 7 days (after the next 24 h)
    submitted: list[HomeworkItem]  # Canvas recorded a submission in the last 7 days


class HomeworkOpened(BaseModel):
    action: ActionRun
    replayed: bool


class HomeworkCheck(BaseModel):
    job_ids: list[str]


class HomeworkWeek(BaseModel):
    """One week (Monday to Sunday, local) of homework, by due date (T-0069)."""

    start: date  # the Monday
    on_time: int  # handed in, Canvas did not mark it late
    late: int  # handed in late
    missing: int  # Canvas marks it missing
    open: int  # not handed in and not due yet


class HomeworkWeeks(BaseModel):
    weeks: list[HomeworkWeek]  # oldest first; the last one is this week
