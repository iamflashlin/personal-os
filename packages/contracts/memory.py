"""Memory (second brain) API types (HANDOFF §4.3, VISION direction 1)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Body = Annotated[str, Field(min_length=1, max_length=20_000)]
SourceRef = Annotated[str, Field(max_length=2_000)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class MemoryKind(StrEnum):
    preference = "preference"
    fact = "fact"
    decision = "decision"
    experience = "experience"


class Provenance(StrEnum):
    raw = "raw"  # captured as said, not interpreted
    user_confirmed = "user_confirmed"  # the user explicitly confirmed or corrected it
    ai_inferred = "ai_inferred"  # a model guessed it; treat with care
    verified = "verified"  # backed by Evidence (S6); cannot be set through the API


class Sensitivity(StrEnum):
    normal = "normal"
    private = "private"  # body kept out of the audit log
    secret = "secret"  # also left out of search unless include_secret=true


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryCreate(_Strict):
    kind: MemoryKind
    body: Body
    provenance: Provenance = Provenance.raw
    confidence: Confidence = 1.0
    sensitivity: Sensitivity = Sensitivity.normal
    expires_at: datetime | None = Field(
        default=None, description="Timezone-aware; the memory is hidden from search after it."
    )
    source_ref: SourceRef = Field(
        default="", description="Where it came from: a URL, a file, a chat."
    )


class MemoryUpdate(_Strict):
    """A correction: send only what changes, plus the `version` you last read."""

    version: int = Field(ge=1)
    kind: MemoryKind | None = None
    body: Body | None = None
    provenance: Provenance | None = None
    confidence: Confidence | None = None
    sensitivity: Sensitivity | None = None
    expires_at: datetime | None = None
    source_ref: SourceRef | None = None


class MemoryConfirm(_Strict):
    version: int = Field(ge=1)


class Memory(BaseModel):
    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    source: str
    version: int
    kind: MemoryKind
    body: str
    provenance: Provenance
    confidence: float
    sensitivity: Sensitivity
    expires_at: datetime | None
    source_ref: str


class MemoryHit(BaseModel):
    memory: Memory
    rank: float | None = Field(
        description="bm25 score (lower is better); null for substring-only matches"
    )
