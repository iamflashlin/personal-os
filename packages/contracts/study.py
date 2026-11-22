"""开始学习: a study plan per course, run on the PC by the desktop agent (ADR 0042)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.actions import ActionName, ActionRunStatus


class StudyStep(BaseModel):
    """One thing to open. `params` are the action's own, validated when it is dispatched."""

    label: str  # what the user reads: "打开 3.4 的讲义"
    action: ActionName
    params: dict[str, Any]


class NextUp(BaseModel):
    """What to study now and why."""

    key: str  # the section key in the course map, "" when there is no section to suggest
    title: str  # "复习 3.4 Chain rule"
    why: str  # why this one, e.g. the review reason and the days left to the exam
    page: int | None  # in the course notes
    exam: str  # the exam this prepares for, "" without one


class LastSession(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    title: str  # what that session was for


class StudyPlan(BaseModel):
    course_code: str
    next: NextUp
    steps: list[StudyStep]
    last: LastSession | None  # the course's previous session: where you left off


class StudyStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_code: Annotated[str, Field(min_length=2, max_length=32)]


class StepStatus(StrEnum):
    """`not_sent`: the agent was gone before this step was sent; nothing ran."""

    dispatched = "dispatched"
    succeeded = "succeeded"
    failed = "failed"
    needs_user = "needs_user"
    cancelled = "cancelled"
    lost = "lost"
    not_sent = "not_sent"


class StepRun(BaseModel):
    label: str
    action_run_id: str | None
    status: StepStatus
    message: str


class StudySessionStatus(StrEnum):
    started = "started"
    finished = "finished"


class StudySession(BaseModel):
    id: str
    course_code: str
    status: StudySessionStatus
    next: NextUp
    steps: list[StepRun]
    started_at: datetime
    finished_at: datetime | None
    note: str
    version: int


class StudyFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    note: Annotated[str, Field(max_length=1000)] = ""


def step_status(run: ActionRunStatus) -> StepStatus:
    return StepStatus(run.value)
