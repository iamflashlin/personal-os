"""What the model must return for one email. Long strings are cut, not rejected, so a
wordy answer costs no retry."""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict


def _cut(limit: int) -> BeforeValidator:
    def cut(value: Any) -> Any:
        return value[:limit] if isinstance(value, str) else value

    return BeforeValidator(cut)


def _date_or_none(value: Any) -> Any:
    return None if value in ("", "null", "none", "None") else value


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gist: Annotated[str, _cut(200)]
    action_needed: bool
    action: Annotated[str, _cut(200)] = ""
    deadline_text: Annotated[str, _cut(100)] = ""
    deadline_date: Annotated[date | None, BeforeValidator(_date_or_none)] = None
    importance: Literal["high", "normal", "low"] = "normal"
