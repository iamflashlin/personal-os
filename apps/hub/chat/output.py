"""The model's answer to a mail question, validated before anything uses it (T-0030)."""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict

MAX_ANSWER = 1500


def _cut(text: Any) -> str:
    return str(text or "")[:MAX_ANSWER]


def _refs(value: Any) -> list[str]:
    """Short refs like "m3"; anything that is not a string is dropped."""
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str)][:20]


class ChatOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    answer: Annotated[str, BeforeValidator(_cut)]
    cited: Annotated[list[str], BeforeValidator(_refs)] = []
