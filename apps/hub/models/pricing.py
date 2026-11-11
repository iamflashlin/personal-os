"""Model prices with their source and date (ADR 0025).

Cost is always computed at PEAK rates, so the recorded spend never undercounts. Money is
integer micro-USD (1 USD = 1_000_000), always rounded up.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SOURCE = "https://api-docs.deepseek.com/quick_start/pricing, read on 2026-11-11"
AS_OF = date(2026, 11, 11)
MICRO = 1_000_000


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input_miss: Decimal
    input_hit: Decimal
    output: Decimal


PEAK: dict[tuple[str, str], Price] = {
    ("deepseek", "deepseek-flash"): Price(Decimal("0.30"), Decimal("0.006"), Decimal("1.20")),
    # FakeProvider only (tests and offline verification), priced like deepseek-flash.
    ("fake", "fake"): Price(Decimal("0.30"), Decimal("0.006"), Decimal("1.20")),
}
# Documentation only: off-peak is half of peak (01:00-04:00 and 06:00-10:00 UTC Mon-Fri are
# peak). It is not used for billing.
OFF_PEAK: dict[tuple[str, str], Price] = {
    ("deepseek", "deepseek-flash"): Price(Decimal("0.15"), Decimal("0.003"), Decimal("0.60")),
}


def price(vendor: str, model: str) -> Price | None:
    return PEAK.get((vendor, model))


def micro_usd(tokens: int, usd_per_million: Decimal) -> Decimal:
    """Exact micro-USD for `tokens` at a per-1M price (USD/1M tokens = micro-USD/token)."""
    return Decimal(tokens) * usd_per_million


def round_up(value: Decimal) -> int:
    return math.ceil(value)
