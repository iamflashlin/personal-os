"""Academic OS (ADR 0041): the course knowledge map, exams and mastery.

The course structure (chapters, sections, concepts) is objective teaching data from the
teacher's materials. Mastery is the user's own state and is stored apart, so a shared map
never carries one student's results. Every concept keeps where it comes from; whatever
the assistant added (such as a prerequisite it inferred) says so (`origin`).
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.academic import check_pattern

ConceptKind = Literal["chapter", "section", "concept"]
Origin = Literal["teacher", "ai"]  # ai: added by the assistant, never the teacher's words
MasteryState = Literal["not_tested", "seen", "practicing", "verified", "needs_review"]


class ConceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(min_length=1, max_length=40)  # "3.4", "3.4-chain", "ch3"
    kind: ConceptKind
    parent: str = Field(default="", max_length=40)
    title: str = Field(min_length=1, max_length=200)
    title_zh: str = Field(default="", max_length=200)
    page: int | None = Field(default=None, ge=1, le=5000)  # in the course material
    prereq: list[str] = Field(default_factory=list, max_length=12)
    prereq_origin: Origin = "ai"
    origin: Origin = "teacher"
    # For a section whose Canvas work does not carry its number (ECON: "Homework - Monetary
    # Policy"): whole-title patterns (`title_pattern`) of its assignments and module items.
    match: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("match")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        v = [" ".join(p.split()) for p in v]  # titles are matched with single spaces
        for p in v:
            if not p or len(p) > 120:
                raise ValueError("a title pattern has 1 to 120 characters")
            check_pattern(p)
        return v

    @model_validator(mode="after")
    def _only_sections_match(self) -> "ConceptIn":
        if self.match and self.kind != "section":
            raise ValueError(f"{self.key}: only a section links work by title")
        return self


class CheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=400)
    source: str = Field(default="", max_length=400)


class ExamIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    at: AwareDatetime | None = None
    scope: list[str] = Field(min_length=1, max_length=80)  # chapter or section keys
    scope_source: str = Field(default="", max_length=400)
    # The exam's own Canvas title (title_pattern). Required: without it the exam would be
    # counted as practice for the sections its title names.
    match: str = Field(min_length=1, max_length=120)
    review: str = Field(default="", max_length=200)  # the review sheet's file name

    @field_validator("match")
    @classmethod
    def _pattern(cls, v: str) -> str:
        return check_pattern(v)


class MapIn(BaseModel):
    """One course's whole map, as an import writes it (replaces the previous one)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    course_code: str = Field(min_length=2, max_length=32)
    material: str = Field(default="", max_length=200)  # the main notes' file name
    note: str = Field(default="", max_length=600)
    concepts: list[ConceptIn] = Field(min_length=1, max_length=600)
    exams: list[ExamIn] = Field(default_factory=list, max_length=20)
    exam_checklist: list[CheckItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _consistent(self) -> "MapIn":
        keys = [c.key for c in self.concepts]
        if len(set(keys)) != len(keys):
            raise ValueError("a concept key appears twice")
        known = set(keys)
        for c in self.concepts:
            if c.parent and c.parent not in known:
                raise ValueError(f"{c.key}: unknown parent {c.parent}")
            for p in c.prereq:
                if p not in known:
                    raise ValueError(f"{c.key}: unknown prerequisite {p}")
        kinds = {c.key: c.kind for c in self.concepts}
        if sum(len(c.match) for c in self.concepts) > 200:
            raise ValueError("at most 200 title patterns in a map")
        names = [e.name for e in self.exams]
        if len(set(names)) != len(names):
            raise ValueError("an exam name appears twice")
        for e in self.exams:
            for s in e.scope:
                if kinds.get(s) not in ("chapter", "section"):
                    raise ValueError(f"{e.name}: scope {s} is not a chapter or section")
        return self


class AssessmentEvidence(BaseModel):
    """A graded Canvas assessment that covers a section."""

    title: str
    score: float | None
    points: float | None
    percent: float | None
    due: datetime | None
    url: str


class Resource(BaseModel):
    """A Canvas module item for a section or an exam (the teacher's link)."""

    title: str
    kind: str  # File | Page | ExternalUrl | ExternalTool
    url: str


class MasteryView(BaseModel):
    state: MasteryState
    source: Literal["user", "quiz", "none"]  # set by the user, inferred from scores, or no data
    note: str
    updated_at: datetime | None


class ConceptView(BaseModel):
    key: str
    kind: ConceptKind
    parent: str
    title: str
    title_zh: str
    page: int | None
    material_url: str  # the Canvas link of the notes, "" when not synced
    prereq: list[str]
    prereq_origin: Origin
    origin: Origin
    assessments: list[AssessmentEvidence]  # only for sections
    resources: list[Resource]  # the teacher's per-section items (e.g. "Math1A-Sec3.4")
    mastery: MasteryView | None  # only for sections and concepts


class ExamView(BaseModel):
    name: str
    at: datetime | None
    days_left: int | None
    scope: list[str]  # section keys (chapters expanded)
    scope_source: str
    review: str
    review_url: str
    resources: list[Resource]  # module items named after the exam (review, solution)
    grade: AssessmentEvidence | None  # the exam's own Canvas assignment, once it has a score


class CourseMap(BaseModel):
    course_code: str
    material: str
    note: str
    concepts: list[ConceptView]
    exams: list[ExamView]
    checklist: list[CheckItem]


class ExamMap(BaseModel):
    """One exam's review map: its sections, the prerequisites outside its scope, and the
    order the assistant suggests (weakest evidence first)."""

    course_code: str
    exam: ExamView
    sections: list[ConceptView]  # in scope, in teaching order
    prerequisites: list[ConceptView]  # outside the scope but needed by it
    suggested: list[str]  # section keys, review these first (with the reason in `why`)
    why: dict[str, str]
    checklist: list[CheckItem]


class MasteryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state: MasteryState
    note: str = Field(default="", max_length=400)
