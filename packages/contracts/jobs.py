"""Background jobs run by the Hub (HANDOFF §4.3, ADR 0017).

Jobs are delivered at least once: a job interrupted by a crash runs again, so every
handler must be idempotent.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class JobStatus(StrEnum):
    queued = "queued"  # waiting for run_at; also after a failed attempt that will retry
    running = "running"
    succeeded = "succeeded"
    dead = "dead"  # gave up: out of attempts, or a kind nobody handles


class Job(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    run_at: datetime
    idempotency_key: str | None
    last_error: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class Schedule(BaseModel):
    """Enqueue one `kind` job every `interval_s` seconds."""

    id: str
    kind: str
    payload: dict[str, Any]
    interval_s: int
    next_run_at: datetime
    enabled: bool
    created_at: datetime
    updated_at: datetime
    version: int
