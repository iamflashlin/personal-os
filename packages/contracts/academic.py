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


TITLE_MAX = 300  # longer Canvas titles are cut before matching


def title_pattern(match: str) -> re.Pattern[str]:
    """A category's title pattern: the whole title, ignoring case, where `#` is a number
    and `*` is anything. No user-written regular expression reaches `re` (no ReDoS)."""
    parts = []
    for ch in match.strip():
        parts.append(r"\d+" if ch == "#" else ".*" if ch == "*" else re.escape(ch))
    return re.compile("".join(parts), re.IGNORECASE)


_CANVAS_CODE = re.compile(r"\b([A-Z]{2,5})\s+([A-Z]?\d{3,4}[A-Z]?)\b")


def canvas_course_code(raw: str) -> str:
    """'F26 MATH D001A 49 Calculus I' -> 'MATH D001A' ("" when there is none)."""
    m = _CANVAS_CODE.search(raw or "")
    return f"{m.group(1)} {m.group(2)}" if m else ""


def normal_code(code: str) -> str:
    """'math  d001a' and 'MATH D001A' name the same course."""
    return " ".join(code.upper().split())


class GradeCategory(BaseModel):
    """One graded category of the syllabus. `match` picks its Canvas assignments by their
    whole title (see `title_pattern`: `ZB#` matches ZB01, `ZB# Lab` matches ZB01 Lab);
    empty means the Canvas group of the same name."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    weight: float = Field(gt=0, le=100)
    match: str = Field(default="", max_length=120)

    @field_validator("match")
    @classmethod
    def _pattern(cls, v: str) -> str:
        if "**" in v or "##" in v:
            raise ValueError("write * or # once")
        if v.count("*") + v.count("#") > 3:
            raise ValueError("at most three * or # in a pattern")
        return v


class CourseRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: RuleKind
    text: str = Field(min_length=1, max_length=600)  # plain Chinese, for the user
    source: str = Field(default="", max_length=600)  # the syllabus words it comes from


class ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=32)  # "MATH D001A", as course_code() gives it

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return normal_code(v)

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
        if self.scale and self.scale[-1].min != 0:
            raise ValueError("the scale must go down to 0 (the lowest letter starts at 0)")
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
