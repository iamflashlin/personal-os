"""Calling a language model with a cost record and a monthly budget (ADR 0025).

`ModelClient.call_json`:
1. estimate an upper bound for the call;
2. insert a `reserved` row at the estimate; if this month's spend including it exceeds the
   cap, roll back and refuse with `ModelUnavailable("budget")` before any request (the
   INSERT holds SQLite's write lock, so concurrent reservations, even from another
   process, are serialised);
3. commit the reservation;
4. call the provider;
5. settle the row: `ok` at the actual peak-rate cost, or `error` (0 when the vendor
   answered with an error status, the estimate when it may have billed);
6. validate the output against a Pydantic model.
"""

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, NotFound
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.models import pricing
from apps.hub.models.deepseek import DeepSeekProvider
from apps.hub.models.fake import FakeProvider
from apps.hub.models.models import ModelCallRow
from apps.hub.models.prompts import Prompt, load_prompt
from apps.hub.models.provider import (
    JsonRequest,
    ModelProvider,
    ProviderError,
    ProviderErrorKind,
    Usage,
)
from packages.contracts.models import ModelUsage

logger = logging.getLogger(__name__)

CREDENTIAL = "deepseek"
ENTITY = "model_call"
TEMPLATE_OVERHEAD_TOKENS = 64  # chat-template tokens around the two messages
# Serialises reservations inside this process; SQLite's write lock covers other processes.
_RESERVE_LOCK = threading.Lock()

UnavailableReason = Literal[
    "no_key", "key_rejected", "no_balance", "rate_limited", "budget", "unpriced"
]
_UNAVAILABLE: dict[ProviderErrorKind, UnavailableReason] = {
    ProviderErrorKind.auth: "key_rejected",
    ProviderErrorKind.no_balance: "no_balance",
    ProviderErrorKind.rate_limit: "rate_limited",
}
_RETRYABLE = {ProviderErrorKind.transient, ProviderErrorKind.bad_output}


class ModelUnavailable(Exception):
    """No call can succeed right now; trying the next item will not help."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason)
        self.reason: UnavailableReason = reason


class ModelFailed(Exception):
    """This call failed; `retryable` says whether the same input may work later."""

    def __init__(self, kind: ProviderErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = kind in _RETRYABLE


def provider_from_settings(settings: Settings) -> ModelProvider:
    if settings.model_provider == "fake":
        return FakeProvider()
    return DeepSeekProvider(settings.model_base_url)


def model_name(settings: Settings) -> str:
    """The model to ask for: FakeProvider has its own priced name."""
    return "fake" if settings.model_provider == "fake" else settings.model_name


def budget_micro_usd(settings: Settings) -> int:
    return math.ceil(settings.ai_budget_usd * pricing.MICRO)


def _price(vendor: str, model: str) -> pricing.Price:
    found = pricing.price(vendor, model)
    if found is None:
        raise ModelUnavailable("unpriced")
    return found


def estimate_micro_usd(vendor: str, model: str, system: str, user: str, max_output: int) -> int:
    """An upper bound: a byte-level BPE token is at least one UTF-8 byte."""
    p = _price(vendor, model)
    input_bound = len(system.encode("utf-8")) + len(user.encode("utf-8"))
    input_bound += TEMPLATE_OVERHEAD_TOKENS
    exact = pricing.micro_usd(input_bound, p.input_miss) + pricing.micro_usd(max_output, p.output)
    return pricing.round_up(exact)


def cost_micro_usd(vendor: str, model: str, usage: Usage) -> int:
    p = _price(vendor, model)
    miss = max(0, usage.input_tokens - usage.cached_input_tokens)
    exact = (
        pricing.micro_usd(miss, p.input_miss)
        + pricing.micro_usd(usage.cached_input_tokens, p.input_hit)
        + pricing.micro_usd(usage.output_tokens, p.output)
    )
    return pricing.round_up(exact)


def month_start(now: datetime) -> datetime:
    utc = now.astimezone(UTC)
    return datetime(utc.year, utc.month, 1, tzinfo=UTC)


def _next_month(start: datetime) -> datetime:
    return start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)


def month_spent_micro_usd(session: Session, actor: Actor, now: datetime) -> int:
    start = month_start(now)
    total = session.scalar(
        select(func.coalesce(func.sum(ModelCallRow.cost_micro_usd), 0)).where(
            ModelCallRow.owner_id == actor.owner_id,
            ModelCallRow.created_at >= start,
            ModelCallRow.created_at < _next_month(start),
        )
    )
    return int(total or 0)


def remaining_micro_usd(session: Session, actor: Actor, now: datetime, budget: int) -> int:
    return max(0, budget - month_spent_micro_usd(session, actor, now))


def has_key(session: Session, actor: Actor) -> bool:
    return any(c.name == CREDENTIAL for c in credentials.list_all(session, actor))


def last_error(session: Session, actor: Actor) -> str:
    """The newest call's account-level failure, or "" when the newest call was fine.
    The next call (e.g. `POST /summaries/run` after a new key) replaces it."""
    newest = session.scalars(
        select(ModelCallRow)
        .where(ModelCallRow.owner_id == actor.owner_id)
        .order_by(ModelCallRow.created_at.desc(), ModelCallRow.id.desc())
        .limit(1)
    ).first()
    if newest is None or newest.status != "error":
        return ""
    kind = ProviderErrorKind(newest.error_kind) if newest.error_kind else None
    return _UNAVAILABLE.get(kind, "") if kind else ""


def usage(
    session: Session, actor: Actor, now: datetime, budget: int, vendor: str, model: str
) -> ModelUsage:
    start = month_start(now)
    calls = session.scalar(
        select(func.count(ModelCallRow.id)).where(
            ModelCallRow.owner_id == actor.owner_id,
            ModelCallRow.created_at >= start,
            ModelCallRow.created_at < _next_month(start),
        )
    )
    return ModelUsage(
        vendor=vendor,
        model=model,
        key_set=has_key(session, actor),
        month=start.strftime("%Y-%m"),
        spent_micro_usd=month_spent_micro_usd(session, actor, now),
        budget_micro_usd=budget,
        calls=int(calls or 0),
        last_error=last_error(session, actor),
        prices_as_of=pricing.AS_OF,
    )


@dataclass
class ModelClient:
    """One job run's handle on the model: the key is revealed once, when it is opened."""

    engine: Engine
    actor: Actor
    provider: ModelProvider
    model: str
    budget: int
    clock: Callable[[], datetime]
    _key: str = field(repr=False)

    def call_json[T: BaseModel](
        self,
        prompt: Prompt,
        variables: Mapping[str, str],
        output: type[T],
        *,
        purpose: str,
        ref: str,
        max_output_tokens: int,
    ) -> tuple[T, str]:
        """The validated output and the `model_call` row id."""
        user = prompt.render(variables)
        vendor = self.provider.vendor
        estimate = estimate_micro_usd(vendor, self.model, prompt.system, user, max_output_tokens)
        call_id = self._reserve(prompt, purpose, ref, estimate)
        started = time.monotonic()

        def latency() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            reply = self.provider.complete_json(
                JsonRequest(self.model, prompt.system, user, max_output_tokens), self._key
            )
        except ProviderError as exc:
            self._settle_error(call_id, exc, estimate, latency())
            if exc.kind in _UNAVAILABLE:
                raise ModelUnavailable(_UNAVAILABLE[exc.kind]) from None
            raise ModelFailed(exc.kind, str(exc)) from None
        except Exception as exc:
            # Anything the adapter did not map: count it as possibly billed, never leak it.
            failure = ProviderError(
                ProviderErrorKind.transient, type(exc).__name__, maybe_billed=True
            )
            self._settle_error(call_id, failure, estimate, latency())
            raise ModelFailed(ProviderErrorKind.transient, str(failure)) from None
        try:
            parsed = output.model_validate_json(reply.text)
        except ValidationError:
            failure = ProviderError(
                ProviderErrorKind.bad_output,
                "output failed the schema",
                maybe_billed=True,  # the vendor returned content, so it billed
                usage=reply.usage,
            )
            self._settle_error(call_id, failure, estimate, latency())
            raise ModelFailed(ProviderErrorKind.bad_output, str(failure)) from None
        self._settle_ok(
            call_id, reply.usage, estimate, latency(), reply.finish_reason, reply.request_id
        )
        return parsed, call_id

    def _reserve(self, prompt: Prompt, purpose: str, ref: str, estimate: int) -> str:
        """Insert first, then check: the INSERT takes SQLite's write lock, so a second
        writer (this process or another) waits and then sees this row in its sum.

        This relies on `core.db` issuing a plain deferred BEGIN and on the INSERT being the
        transaction's first statement: do not add a SELECT before the flush, or a WAL
        snapshot taken by it could miss a concurrent reservation."""
        with _RESERVE_LOCK, Session(self.engine) as session:
            now = self.clock()
            row = ModelCallRow(
                owner_id=self.actor.owner_id,
                source=self.actor.source,
                version=1,
                created_at=now,
                updated_at=now,
                vendor=self.provider.vendor,
                model=self.model,
                purpose=purpose[:32],
                ref=ref[:64],
                prompt_name=prompt.name[:64],
                prompt_version=prompt.version,
                prompt_sha=prompt.sha256,
                status="reserved",
                estimate_micro_usd=estimate,
                cost_micro_usd=estimate,
            )
            session.add(row)
            session.flush()
            if month_spent_micro_usd(session, self.actor, now) > self.budget:
                session.rollback()
                raise ModelUnavailable("budget")
            session.commit()
            return row.id

    def _charge(self, used: Usage | None, estimate: int) -> int:
        """Actual peak-rate cost, but never below the estimate when usage is missing:
        an unreadable usage block must not make a billed call look free."""
        if used is None or used.input_tokens == 0:
            return estimate
        return cost_micro_usd(self.provider.vendor, self.model, used)

    def _settle_ok(
        self,
        call_id: str,
        used: Usage | None,
        estimate: int,
        latency: int,
        finish_reason: str,
        request_id: str,
    ) -> None:
        cost = self._charge(used, estimate)
        if cost > estimate:
            logger.warning(
                "model call %s cost %s micro-USD, above its estimate %s", call_id, cost, estimate
            )
        self._settle(
            call_id,
            "ok",
            cost,
            used or Usage(0, 0, 0),
            latency,
            finish_reason[:32],
            request_id,
            None,
        )

    def _settle_error(self, call_id: str, exc: ProviderError, estimate: int, latency: int) -> None:
        if exc.usage is not None:
            cost = self._charge(exc.usage, estimate)
        else:
            cost = estimate if exc.maybe_billed else 0
        used = exc.usage or Usage(0, 0, 0)
        self._settle(call_id, "error", cost, used, latency, "", "", exc)

    def _settle(
        self,
        call_id: str,
        status: str,
        cost: int,
        used: Usage,
        latency: int,
        finish_reason: str,
        request_id: str,
        exc: ProviderError | None,
    ) -> None:
        kind = exc.kind.value if exc is not None else ""
        with Session(self.engine) as session:
            row = session.get(ModelCallRow, call_id)
            if row is None:  # pragma: no cover - the row was committed by _reserve
                return
            row.status = status
            row.cost_micro_usd = cost
            row.input_tokens = used.input_tokens
            row.cached_input_tokens = used.cached_input_tokens
            row.output_tokens = used.output_tokens
            row.latency_ms = latency
            row.finish_reason = finish_reason
            row.request_id = request_id
            row.updated_at = self.clock()
            if exc is not None:
                row.error_kind = kind
                row.error = audit.redact_text(str(exc))[:500]
            audit.record(
                session,
                owner_id=self.actor.owner_id,
                actor=self.actor.name,
                action=f"{ENTITY}.call",
                entity_type=ENTITY,
                entity_id=call_id,
                result=status,
                detail={
                    "purpose": row.purpose,
                    "ref": row.ref,
                    "model": row.model,
                    "input_tokens": used.input_tokens,
                    "output_tokens": used.output_tokens,
                    "cost_micro_usd": cost,
                    "estimate_micro_usd": row.estimate_micro_usd,
                    "over_estimate": cost > row.estimate_micro_usd,
                    "error_kind": kind,
                },
            )
            session.commit()
        if status == "error":
            logger.warning("model call %s failed: %s", call_id, kind)


def open_client(
    engine: Engine,
    actor: Actor,
    store: credentials.SecretStore,
    provider: ModelProvider,
    model: str,
    budget: int,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ModelClient:
    """Reveal the key once (audited); `ModelUnavailable("no_key")` when it is not set."""
    _price(provider.vendor, model)
    with Session(engine) as session:
        try:
            key = credentials.reveal(session, actor, store, CREDENTIAL)
        except NotFound:
            raise ModelUnavailable("no_key") from None
    return ModelClient(engine, actor, provider, model, budget, clock, key)


# What other modules may use from this package (they import only `service`, ADR 0005).
__all__ = [
    "CREDENTIAL",
    "ModelClient",
    "ModelFailed",
    "ModelProvider",
    "ModelUnavailable",
    "Prompt",
    "budget_micro_usd",
    "estimate_micro_usd",
    "has_key",
    "last_error",
    "load_prompt",
    "model_name",
    "open_client",
    "provider_from_settings",
    "remaining_micro_usd",
    "usage",
]
