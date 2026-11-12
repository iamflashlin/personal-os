"""Academic OS (ADR 0040): what each course's syllabus says, kept apart from Canvas.

A course profile holds the rules the grade engine must follow: units, the letter scale,
the graded categories and their weights, and rules such as "no late work". Each rule keeps
where it came from, because the syllabus (not Canvas) is the authority and the user checks
the profile once (`confirmed_at`).
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# De Anza's grade points (deanza.edu/policies/grades): A+ and A are both 4.0; no C-.
GRADE_POINTS: dict[str, float] = {
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "D+": 1.3,
    "D": 1.0,
    "D-": 0.7,
    "F": 0.0,
}

RuleKind = Literal["late", "makeup", "exam", "gate", "integrity", "grading", "other"]


class GradeBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    letter: str
    min: float = Field(ge=0, le=100)  # the lowest course percent that earns this letter

    @field_validator("letter")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in GRADE_POINTS:
            raise ValueError(f"unknown letter {v}")
        return v


class GradeCategory(BaseModel):
    """One graded category of the syllabus. `match` picks its Canvas assignments by title
    (a case-insensitive regular expression); empty means the Canvas group of the same name."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    weight: float = Field(gt=0, le=100)
    match: str = Field(default="", max_length=200)

    @field_validator("match")
    @classmethod
    def _regex(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"bad pattern: {exc}") from None
        return v


class CourseRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: RuleKind
    text: str = Field(min_length=1, max_length=600)  # plain Chinese, for the user
    source: str = Field(default="", max_length=600)  # the syllabus words it comes from


class ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=32)  # "MATH D001A", as course_code() gives it
    title: str = Field(default="", max_length=200)
    term: str = Field(default="", max_length=40)
    units: float | None = Field(default=None, gt=0, le=10)
    units_source: str = Field(default="", max_length=300)
    scale: list[GradeBand] = Field(default_factory=list)
    scale_source: str = Field(default="", max_length=300)
    # Empty: Canvas's own groups and weights already match the syllabus.
    categories: list[GradeCategory] = Field(default_factory=list)
    rules: list[CourseRule] = Field(default_factory=list, max_length=40)
    open_questions: list[str] = Field(default_factory=list, max_length=20)  # 待确认
    syllabus_source: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _consistent(self) -> "ProfileFields":
        if self.categories and abs(sum(c.weight for c in self.categories) - 100) > 0.01:
            raise ValueError("category weights must add up to 100")
        mins = [b.min for b in self.scale]
        if mins != sorted(mins, reverse=True):
            raise ValueError("the scale must go from the highest letter down")
        if len({b.letter for b in self.scale}) != len(self.scale):
            raise ValueError("a letter appears twice in the scale")
        return self


class CourseProfile(ProfileFields):
    id: str
    confirmed_at: datetime | None  # when the user checked it against the syllabus
    origin: str
    updated_at: datetime
    version: int


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: ProfileFields
    version: int | None = None  # None creates; otherwise the version being replaced


class ProfileConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int


def letter_for(scale: list[GradeBand], percent: float) -> str | None:
    """The letter a course percent earns on this scale (None without a scale)."""
    for band in scale:
        if percent >= band.min:
            return band.letter
    return None
