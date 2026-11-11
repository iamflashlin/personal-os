"""Language-model usage as the web UI sees it (ADR 0025)."""

from datetime import date

from pydantic import BaseModel


class ModelUsage(BaseModel):
    vendor: str
    model: str
    key_set: bool
    month: str  # "2026-11", the UTC calendar month the budget covers
    spent_micro_usd: int
    budget_micro_usd: int
    calls: int
    last_error: str  # "" | "key_rejected" | "no_balance" | "rate_limited"
    prices_as_of: date
