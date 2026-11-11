"""Evidence that a task is really done (CLAUDE.md: never done from model output alone)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class EvidenceKind(StrEnum):
    # A person confirmed it in a UI. Build/test output, commits and files arrive in S6.
    user_confirmation = "user_confirmation"


class TaskCompletion(BaseModel):
    """Body of POST /tasks/{id}/complete."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="The task version you last read.")
    note: Annotated[str, Field(max_length=2_000)] = ""


class Evidence(BaseModel):
    id: str
    task_id: str
    kind: EvidenceKind
    note: str
    created_at: datetime
    source: str
