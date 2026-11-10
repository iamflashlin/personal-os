"""Goal / Project / Task / Workspace API types (HANDOFF §4.3).

`<Kind>Create` is the full writable state. `<Kind>Update` is a PATCH: send only the
fields to change plus the `version` you last read; a stale `version` gets HTTP 409.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Title = Annotated[str, Field(min_length=1, max_length=200)]
Notes = Annotated[str, Field(max_length=20_000)]
Ref = Annotated[str, Field(min_length=26, max_length=26)]
Item = Annotated[str, Field(min_length=1, max_length=2_000)]

CIS_COURSE_TAG = "course:CIS"


class WorkStatus(StrEnum):
    active = "active"
    paused = "paused"
    done = "done"
    dropped = "dropped"


class TaskStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


class ExecutionMode(StrEnum):
    delegate = "delegate"
    collaborate = "collaborate"
    human_led = "human_led"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Update(_Strict):
    version: int = Field(ge=1)


class _Stored(BaseModel):
    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    source: str
    version: int


class GoalCreate(_Strict):
    title: Title
    notes: Notes = ""
    status: WorkStatus = WorkStatus.active
    due_date: date | None = None


class GoalUpdate(_Update):
    title: Title | None = None
    notes: Notes | None = None
    status: WorkStatus | None = None
    due_date: date | None = None


class Goal(_Stored, GoalCreate):
    pass


class ProjectCreate(_Strict):
    goal_id: Ref | None = None
    title: Title
    notes: Notes = ""
    status: WorkStatus = WorkStatus.active
    due_date: date | None = None


class ProjectUpdate(_Update):
    goal_id: Ref | None = None
    title: Title | None = None
    notes: Notes | None = None
    status: WorkStatus | None = None
    due_date: date | None = None


class Project(_Stored, ProjectCreate):
    pass


class _TaskFields(_Strict):
    project_id: Ref | None = None
    title: Title
    notes: Notes = ""
    status: TaskStatus = TaskStatus.todo
    due_date: date | None = None
    tags: list[Item] = Field(default_factory=list[str], max_length=50)
    depends_on: list[Ref] = Field(default_factory=list[str], max_length=100)


class TaskCreate(_TaskFields):
    execution_mode: ExecutionMode | None = Field(
        default=None,
        description=f"Omitted: human_led if tags contain {CIS_COURSE_TAG!r}, else collaborate.",
    )


class TaskUpdate(_Update):
    project_id: Ref | None = None
    title: Title | None = None
    notes: Notes | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    execution_mode: ExecutionMode | None = None
    tags: list[Item] | None = Field(default=None, max_length=50)
    depends_on: list[Ref] | None = Field(default=None, max_length=100)


class Task(_Stored, _TaskFields):
    execution_mode: ExecutionMode


class WorkspaceCreate(_Strict):
    """Bound to exactly one of a project or a task."""

    project_id: Ref | None = None
    task_id: Ref | None = None
    title: Title
    urls: list[Item] = Field(default_factory=list[str], max_length=50)
    folders: list[Item] = Field(default_factory=list[str], max_length=50)
    apps: list[Item] = Field(default_factory=list[str], max_length=50)

    @model_validator(mode="after")
    def _bound_to_exactly_one(self) -> Self:
        if (self.project_id is None) == (self.task_id is None):
            raise ValueError("set exactly one of project_id or task_id")
        return self


class WorkspaceUpdate(_Update):
    project_id: Ref | None = None
    task_id: Ref | None = None
    title: Title | None = None
    urls: list[Item] | None = Field(default=None, max_length=50)
    folders: list[Item] | None = Field(default=None, max_length=50)
    apps: list[Item] | None = Field(default=None, max_length=50)


class Workspace(_Stored, WorkspaceCreate):
    pass
