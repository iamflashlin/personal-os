"""What the model must return for one email (prompt v2, ADR 0029). Long strings are cut,
not rejected, so a wordy answer costs no retry."""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict

TITLE_CHARS = 20
POINT_CHARS = 40
MAX_POINTS = 5


def _cut(limit: int) -> BeforeValidator:
    def cut(value: Any) -> Any:
        return value[:limit] if isinstance(value, str) else value

    return BeforeValidator(cut)


def _date_or_none(value: Any) -> Any:
    return None if value in ("", "null", "none", "None") else value


def _points(value: Any) -> Any:
    """At most MAX_POINTS non-empty lines, each cut to POINT_CHARS."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    lines = [v.strip()[:POINT_CHARS] for v in value if isinstance(v, str) and v.strip()]  # pyright: ignore[reportUnknownVariableType]
    return lines[:MAX_POINTS]


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Annotated[str, _cut(TITLE_CHARS)]
    importance: Literal["high", "normal", "low"] = "normal"
    low_value: bool = False
    points: Annotated[list[str], BeforeValidator(_points)] = []
    action_needed: bool = False
    action: Annotated[str, _cut(200)] = ""
    deadline_text: Annotated[str, _cut(100)] = ""
    deadline_date: Annotated[date | None, BeforeValidator(_date_or_none)] = None
