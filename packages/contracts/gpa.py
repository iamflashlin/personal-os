"""GPA management from Canvas (ADR 0037): one view per course, built from synced items."""

from datetime import datetime

from pydantic import BaseModel


class GroupStatus(BaseModel):
    name: str
    weight: float  # percent of the course grade (0 when the course counts plain points)
    earned: float
    possible: float
    percent: float | None  # None until something in the group is graded
    graded: int
    total: int


class WorkItem(BaseModel):
    item_id: str
    title: str
    due: datetime | None
    points: float | None
    group: str
    state: str  # missing | late | submitted | graded | excused | upcoming | open
    score: float | None
    url: str


class Material(BaseModel):
    title: str
    module: str
    kind: str  # File | Page | ExternalUrl | ExternalTool
    url: str


class GradeLine(BaseModel):
    """What the work not graded yet needs, on average, for the whole course to reach `target`."""

    label: str  # e.g. "A (90%)", shown as is
    target: float
    needed: float | None  # percent; None when nothing is left to grade
    status: str  # safe (already there for any remaining score) | reachable | out_of_reach | done


class Completion(BaseModel):
    due_so_far: int  # assignments whose due time has passed (excused ones left out)
    done: int  # of those: submitted or graded
    missing: int
    late: int


class CourseView(BaseModel):
    integration_item_id: str
    code: str  # "CIS D022A"
    name: str
    url: str
    current_score: float | None  # Canvas's: graded work only
    current_grade: str
    grade_points: float | None
    weighted: bool
    groups: list[GroupStatus]
    completion: Completion
    missing: list[WorkItem]
    upcoming: list[WorkItem]  # due in the next 14 days, soonest first
    recent: list[WorkItem]  # graded in the last 14 days, newest first
    lines: list[GradeLine]
    materials: list[Material]


class GpaView(BaseModel):
    courses: list[CourseView]
    gpa: float | None  # average grade points, every course counted equally
    gpa_note: str
    generated_at: datetime
