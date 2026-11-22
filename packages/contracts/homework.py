"""作业 (ADR 0044): each Canvas assignment's submission state, computed from synced items."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from packages.contracts.actions import ActionRun

HomeworkState = Literal["missing", "soon", "week", "submitted"]


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
