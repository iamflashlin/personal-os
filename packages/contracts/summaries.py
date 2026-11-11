"""AI email summaries as the web UI sees them (ADR 0027)."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from packages.contracts.models import ModelUsage


class SummaryStatus(StrEnum):
    pending = "pending"
    ok = "ok"
    skipped_sensitive = "skipped_sensitive"
    skipped_unreadable = "skipped_unreadable"
    failed = "failed"


class Importance(StrEnum):
    high = "high"
    normal = "normal"
    low = "low"


class EmailSummary(BaseModel):
    id: str
    item_id: str
    status: SummaryStatus
    gist: str  # the AI title: what it is about and its deadline (prompt v2)
    points: list[str] = []  # distilled useful facts, shown before the original text
    low_value: bool = False  # ads, newsletters, notices that need nothing: collapsed
    action_needed: bool
    action: str
    deadline_text: str
    deadline_date: date | None
    importance: Importance
    model: str
    prompt_version: int
    error: str
    created_at: datetime
    updated_at: datetime
    version: int


class SummaryBlock(StrEnum):
    none = "none"
    no_key = "no_key"
    key_rejected = "key_rejected"
    no_balance = "no_balance"
    budget = "budget"
    rate_limited = "rate_limited"


class SummariesStatus(BaseModel):
    pending: int
    blocked: SummaryBlock
    notice: str  # "" when nothing blocks; otherwise one sentence for the user, in Chinese
    usage: ModelUsage


class RunStarted(BaseModel):
    job_id: str
