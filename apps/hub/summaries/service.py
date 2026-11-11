# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Summarise each recent email once (ADR 0027).

A `summaries.email` job run:
1. selects email synced in the last 14 days and makes sure each has a row; a changed
   sender, subject or body resets its row to `pending`;
2. marks, without any model or key, mail that must not be sent (`skipped_sensitive`) or
   cannot be read (`skipped_unreadable`);
3. summarises at most 20 due `pending` mails, oldest first, within 150 s, and queues a
   continuation when more are due.

A missing key, a rejected key, no balance, a rate limit or the monthly budget stops the run
and leaves mail `pending` without burning attempts: the next run tries again. Runs are
queued after every successful sync (each source syncs on its own schedule) and on request
(`POST /summaries/run`, e.g. right after the key is entered), so no schedule of its own is
needed. Other failures retry after 5 and 10 minutes, then the mail is
`failed`.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.credentials import service as credentials
from apps.hub.integrations import service as integrations
from apps.hub.jobs import service as jobs
from apps.hub.models import service as models
from apps.hub.summaries import sensitive
from apps.hub.summaries.models import EmailSummaryRow
from apps.hub.summaries.output import SummaryOutput
from packages.contracts.integrations import SyncedItem
from packages.contracts.summaries import (
    EmailSummary,
    Importance,
    SummariesStatus,
    SummaryBlock,
    SummaryStatus,
)

logger = logging.getLogger(__name__)

JOB = "summaries.email"
WINDOW = timedelta(days=14)
PER_RUN = 20
RUN_DEADLINE_S = 150.0
MAX_ATTEMPTS = 3
RETRY_BASE = timedelta(minutes=5)
MAX_OUTPUT_TOKENS = 600
PROMPT_NAME, PROMPT_VERSION = "email_summary", 1
EMAIL = "email_message"
UNREADABLE_TITLE = "（无法解析的邮件）"
MAX_ITEM_IDS = 200

NOTICES = {
    SummaryBlock.none: "",
    SummaryBlock.no_key: "还没有设置 DeepSeek key",
    SummaryBlock.key_rejected: "DeepSeek key 无效，请重新输入",
    SummaryBlock.no_balance: "DeepSeek 账户余额不足",
    SummaryBlock.budget: "本月 AI 预算已用完",
    SummaryBlock.rate_limited: "DeepSeek 暂时限流，稍后会自动重试",
}


def item_hash(item: SyncedItem) -> str:
    """What the summary depends on: not the read state, which changes without new content."""
    fields = [str(item.data.get("from_address", "")), item.title, item.body]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()


_DELIMITER = re.compile(r"</?\s*email\s*>", re.IGNORECASE)


def _defang(text: str) -> str:
    """A mail cannot close the prompt's <email> block early and speak as the operator."""
    return _DELIMITER.sub("[email-tag]", text)


def variables(item: SyncedItem) -> dict[str, str]:
    """What is sent: sender, subject, receive time, attachment names, body. Never recipients.
    Every mail-controlled value has <email> tags neutralised."""
    name = str(item.data.get("from_name", "")).strip()
    address = str(item.data.get("from_address", "")).strip()
    raw_attachments = item.data.get("attachments")
    names = (
        [str(a) for a in raw_attachments]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if isinstance(raw_attachments, list)
        else []
    )
    return {
        "sender": _defang(f"{name} <{address}>" if name else address),
        "subject": _defang(item.title),
        "received": item.starts_at.isoformat() if item.starts_at else "unknown",
        "attachments": _defang(", ".join(names)) or "无",
        "body": _defang(item.body),
    }


def _read(row: EmailSummaryRow) -> EmailSummary:
    return EmailSummary(
        id=row.id,
        item_id=row.item_id,
        status=SummaryStatus(row.status),
        gist=row.gist,
        action_needed=row.action_needed,
        action=row.action,
        deadline_text=row.deadline_text,
        deadline_date=row.deadline_date,
        importance=Importance(row.importance),
        model=row.model,
        prompt_version=row.prompt_version,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


def request_run(
    session: Session, actor: Actor, now: datetime, idempotency_key: str | None = None
) -> str:
    """Queue a summary run; with a key, asking twice queues one job."""
    return jobs.enqueue(session, actor, JOB, {}, now=now, idempotency_key=idempotency_key).id


def _recent_mail(session: Session, actor: Actor, now: datetime) -> list[SyncedItem]:
    return integrations.items_between(
        session, actor, now - WINDOW, now + timedelta(days=1), item_type=EMAIL
    )


def _reset(row: EmailSummaryRow, digest: str) -> None:
    row.item_hash = digest
    row.status = SummaryStatus.pending.value
    row.gist = row.action = row.deadline_text = row.error = row.model = ""
    row.action_needed = False
    row.deadline_date = None
    row.importance = Importance.normal.value
    row.attempts = 0
    row.next_try_at = None
    row.model_call_id = None
    row.prompt_version = 0


def _triage(item: SyncedItem, row: EmailSummaryRow) -> None:
    """Mark mail that is never sent; needs no key and no model."""
    if item.title == UNREADABLE_TITLE or not item.body.strip():
        row.status = SummaryStatus.skipped_unreadable.value
        row.error = "无法读取正文"
        return
    why = sensitive.reason(item.title, item.body)
    if why is not None:
        row.status = SummaryStatus.skipped_sensitive.value
        row.error = why


def prepare(session: Session, actor: Actor, now: datetime) -> dict[str, SyncedItem]:
    """Rows for every recent mail, triaged. Returns the recent mail by id."""
    items = {i.id: i for i in _recent_mail(session, actor, now)}
    rows = {
        r.item_id: r
        for r in session.scalars(
            select(EmailSummaryRow).where(
                EmailSummaryRow.owner_id == actor.owner_id,
                EmailSummaryRow.item_id.in_(list(items)),
            )
        )
    }
    for item_id, item in items.items():
        digest = item_hash(item)
        row = rows.get(item_id)
        if row is None:
            row = EmailSummaryRow(
                owner_id=actor.owner_id,
                source=actor.source,
                version=1,
                item_id=item_id,
                created_at=now,
                updated_at=now,
            )
            _reset(row, digest)
            session.add(row)
        elif row.item_hash != digest:
            _reset(row, digest)
        else:
            continue
        _triage(item, row)
    session.commit()
    return items


def _due(session: Session, actor: Actor, items: dict[str, SyncedItem], now: datetime) -> list[str]:
    rows = session.scalars(
        select(EmailSummaryRow).where(
            EmailSummaryRow.owner_id == actor.owner_id,
            EmailSummaryRow.status == SummaryStatus.pending.value,
            EmailSummaryRow.item_id.in_(list(items)),
        )
    ).all()
    due = [r for r in rows if r.next_try_at is None or r.next_try_at <= now]
    oldest = datetime.min.replace(tzinfo=UTC)
    due.sort(key=lambda r: (items[r.item_id].starts_at or oldest, r.item_id))
    return [r.id for r in due]


def run(
    engine: Engine,
    store: credentials.SecretStore,
    actor: Actor,
    provider: models.ModelProvider,
    model: str,
    budget: int,
    now: datetime,
    prompt: models.Prompt | None = None,
    clock: Callable[[], datetime] | None = None,
) -> bool:
    """One summary run. Returns True when more mail is due than this run handled."""
    prompt = prompt or models.load_prompt(PROMPT_NAME, PROMPT_VERSION)
    tick = clock or (lambda: now)  # the time of each write; a run can last 150 s
    with Session(engine) as session:
        items = prepare(session, actor, now)
        due = _due(session, actor, items, now)
    if not due:
        return False
    try:
        client = models.open_client(engine, actor, store, provider, model, budget, tick)
    except models.ModelUnavailable as exc:
        if exc.reason != "no_key":  # e.g. an unpriced model: a configuration mistake
            logger.warning("email summaries cannot run: %s", exc.reason)
        return False  # mail stays pending, nothing burnt
    started = time.monotonic()
    handled = 0
    for summary_id in due[:PER_RUN]:
        if time.monotonic() - started > RUN_DEADLINE_S:
            break
        # No transaction stays open across the model call: the call writes `model_call`
        # rows, and a write from a stale WAL snapshot afterwards would fail as busy.
        with Session(engine) as session:
            row = session.get(EmailSummaryRow, summary_id)
            if row is None or row.status != SummaryStatus.pending.value:
                handled += 1  # settled elsewhere: nothing left to do for it
                continue
            item = items[row.item_id]
        try:
            out, call_id = client.call_json(
                prompt,
                variables(item),
                SummaryOutput,
                purpose="email_summary",
                ref=item.id,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except models.ModelUnavailable:
            return False  # budget, key rejected, no balance, rate limit: stop here
        except models.ModelFailed as exc:
            _record_failure(engine, summary_id, exc, tick())
            handled += 1
            continue
        handled += 1
        with Session(engine) as session:
            row = session.get(EmailSummaryRow, summary_id)
            if row is None:  # the mail was deleted during the call
                continue
            row.status = SummaryStatus.ok.value
            row.gist = out.gist
            row.action_needed = out.action_needed
            row.action = out.action if out.action_needed else ""
            row.deadline_text = out.deadline_text
            row.deadline_date = out.deadline_date
            row.importance = out.importance
            row.model_call_id = call_id
            row.model = model
            row.prompt_version = prompt.version
            row.error = ""
            row.next_try_at = None
            row.updated_at = tick()
            session.commit()
    return len(due) > handled


def _record_failure(
    engine: Engine, summary_id: str, exc: models.ModelFailed, now: datetime
) -> None:
    with Session(engine) as session:
        row = session.get(EmailSummaryRow, summary_id)
        if row is None:
            return
        row.attempts += 1
        row.error = exc.kind.value
        if not exc.retryable or row.attempts >= MAX_ATTEMPTS:
            row.status = SummaryStatus.failed.value
            row.next_try_at = None
        else:
            row.next_try_at = now + RETRY_BASE * (2 ** (row.attempts - 1))
        row.updated_at = now
        session.commit()


def run_job(
    engine: Engine,
    store: credentials.SecretStore,
    actor: Actor,
    provider: models.ModelProvider,
    model: str,
    budget: int,
    job_id: str,
    now: datetime,
) -> None:
    """The job handler: one run, then a continuation if more mail is due."""
    if run(engine, store, actor, provider, model, budget, now, clock=lambda: datetime.now(UTC)):
        with Session(engine) as session:
            request_run(session, actor, now, idempotency_key=f"{JOB}:cont:{job_id}")


def summaries_for(
    session: Session, actor: Actor, item_ids: list[str], limit: int | None = MAX_ITEM_IDS
) -> list[EmailSummary]:
    """Summaries of these mails. HTTP callers are capped; Hub views pass `limit=None`."""
    wanted = item_ids if limit is None else item_ids[:limit]
    rows = session.scalars(
        select(EmailSummaryRow).where(
            EmailSummaryRow.owner_id == actor.owner_id,
            EmailSummaryRow.item_id.in_(wanted),
        )
    )
    return [_read(r) for r in rows]


def _blocked(
    session: Session,
    actor: Actor,
    now: datetime,
    budget: int,
    vendor: str,
    model: str,
    prompt: models.Prompt,
    pending: list[EmailSummaryRow],
    items: dict[str, SyncedItem],
) -> SummaryBlock:
    if not models.has_key(session, actor):
        return SummaryBlock.no_key
    if not pending:
        return SummaryBlock.none  # an old error does not matter while nothing waits
    last = models.last_error(session, actor)
    if last:
        return SummaryBlock(last)
    remaining = models.remaining_micro_usd(session, actor, now, budget)
    for row in pending:
        item = items.get(row.item_id)
        if item is None:
            continue
        user = prompt.render(variables(item))
        cost = models.estimate_micro_usd(vendor, model, prompt.system, user, MAX_OUTPUT_TOKENS)
        if cost > remaining:
            return SummaryBlock.budget
    return SummaryBlock.none


def status(
    session: Session,
    actor: Actor,
    now: datetime,
    budget: int,
    vendor: str,
    model: str,
    prompt: models.Prompt | None = None,
) -> SummariesStatus:
    prompt = prompt or models.load_prompt(PROMPT_NAME, PROMPT_VERSION)
    # Only mail still inside the window counts: older pending rows will never be sent.
    items = {i.id: i for i in _recent_mail(session, actor, now)}
    pending = list(
        session.scalars(
            select(EmailSummaryRow).where(
                EmailSummaryRow.owner_id == actor.owner_id,
                EmailSummaryRow.status == SummaryStatus.pending.value,
                EmailSummaryRow.item_id.in_(list(items)),
            )
        )
    )
    blocked = _blocked(session, actor, now, budget, vendor, model, prompt, pending, items)
    return SummariesStatus(
        pending=len(pending),
        blocked=blocked,
        notice=NOTICES[blocked],
        usage=models.usage(session, actor, now, budget, vendor, model),
    )


def count(session: Session, actor: Actor, status_: SummaryStatus) -> int:
    return int(
        session.scalar(
            select(func.count(EmailSummaryRow.id)).where(
                EmailSummaryRow.owner_id == actor.owner_id,
                EmailSummaryRow.status == status_.value,
            )
        )
        or 0
    )
