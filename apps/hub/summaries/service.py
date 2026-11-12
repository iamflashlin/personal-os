# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Summarise each recent email once (ADR 0027).

A `summaries.email` job run:
1. selects email synced in the last 14 days and makes sure each has a row; a changed
   sender, subject or body resets its row to `pending`;
2. marks, without any model or key, mail that must not be sent (`skipped_sensitive`) or
   cannot be read (`skipped_unreadable`);
3. summarises at most 20 due `pending` mails, newest first, within 150 s, and queues a
   continuation when more are due.

All synced mail is covered, not only recent mail (ADR 0031: the user wants all history
summarised once). Newest first, so today's mail is ready while history fills in; the
monthly budget still stops a run before any call that would exceed it.

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
from typing import Any

from sqlalchemy import Engine, and_, func, or_, select
from sqlalchemy.orm import Session

from apps.hub.core.base import utcnow
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
PER_RUN = 20
RUN_DEADLINE_S = 150.0
MAX_ATTEMPTS = 3
RETRY_BASE = timedelta(minutes=5)
MAX_OUTPUT_TOKENS = 600
PROMPT_NAME, PROMPT_VERSION = "email_summary", 3
TITLE_SINCE_VERSION = 2  # from prompt v2 on, `gist` is a short title (ADR 0029)
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
# Tracking links run to hundreds of characters: they cost tokens and say nothing to the
# model. The user still sees them in the original text.
# Only ASCII URL characters: Chinese mail often has no space after a link, and \S would
# swallow the following sentence (and its deadline) along with the link.
_LONG_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]{40,}")
_URL_TAIL = ".,;:!?'"


def _shorten_link(match: re.Match[str]) -> str:
    """A long link becomes 「[链接]」; punctuation that ends the sentence stays."""
    url = match.group(0)
    kept = url.rstrip(_URL_TAIL)
    return "[链接]" + url[len(kept) :]


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
        "body": _defang(_LONG_URL.sub(_shorten_link, item.body)),
    }


def _read(row: EmailSummaryRow) -> EmailSummary:
    return EmailSummary(
        id=row.id,
        item_id=row.item_id,
        status=SummaryStatus(row.status),
        gist=row.gist,
        points=list(row.points or []),
        low_value=row.low_value,
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


Index = dict[str, datetime | None]  # mail id -> when it was received


def _mail_index(session: Session, actor: Actor) -> list[tuple[str, datetime | None, datetime]]:
    """Every synced mail as (id, received, last change), without bodies."""
    return integrations.item_index(session, actor, EMAIL)


def _order(ids: list[str], index: Index) -> list[str]:
    """Newest first; mail without a receive time last."""
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(ids, key=lambda i: (index.get(i) or oldest, i), reverse=True)


def _reset(row: EmailSummaryRow, digest: str) -> None:
    row.item_hash = digest
    row.status = SummaryStatus.pending.value
    row.gist = row.action = row.deadline_text = row.error = row.model = ""
    row.points = []
    row.low_value = False
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


def prepare(session: Session, actor: Actor, now: datetime) -> Index:
    """Rows for every mail, triaged. Only mail that is new, or changed since its row was
    written, has its body loaded, so a run over thousands of mails stays cheap."""
    entries = _mail_index(session, actor)
    rows = {
        r.item_id: r
        for r in session.scalars(
            select(EmailSummaryRow).where(EmailSummaryRow.owner_id == actor.owner_id)
        )
    }
    stale = [
        item_id
        for item_id, _received, changed in entries
        if item_id not in rows or changed > rows[item_id].updated_at
    ]
    for item_id, item in integrations.items_by_id(session, actor, stale).items():
        digest = item_hash(item)
        row = rows.get(item_id)
        if row is None:
            row = EmailSummaryRow(
                owner_id=actor.owner_id,
                source=actor.source,
                version=1,
                item_id=item_id,
                created_at=now,
                updated_at=utcnow(),  # wall clock, like the item it is compared with
            )
            _reset(row, digest)
            session.add(row)
        elif row.item_hash != digest:
            _reset(row, digest)
        else:
            row.updated_at = utcnow()  # checked: unchanged (e.g. only read state moved)
            continue
        _triage(item, row)
    session.commit()
    return {item_id: received for item_id, received, _changed in entries}


def _outdated_filter() -> Any:
    """Rows a newer prompt should redo once: v1 summaries (long sentences, not titles) and
    failures from an older prompt. Good v2+ summaries are kept: redoing them costs money and
    gains nothing."""
    return or_(
        and_(
            EmailSummaryRow.status == SummaryStatus.ok.value,
            EmailSummaryRow.prompt_version < TITLE_SINCE_VERSION,
        ),
        and_(
            EmailSummaryRow.status == SummaryStatus.failed.value,
            EmailSummaryRow.prompt_version < PROMPT_VERSION,
        ),
    )


def _redo_outdated(session: Session, actor: Actor) -> int:
    """Reset summaries from an older prompt so they are redone. Only called once a model
    client is open: without a key or budget, the old summary stays visible."""
    rows = session.scalars(
        select(EmailSummaryRow).where(
            EmailSummaryRow.owner_id == actor.owner_id, _outdated_filter()
        )
    ).all()
    for row in rows:
        _reset(row, row.item_hash)
    session.commit()
    return len(rows)


def _has_outdated(session: Session, actor: Actor) -> bool:
    return (
        session.scalar(
            select(func.count(EmailSummaryRow.id)).where(
                EmailSummaryRow.owner_id == actor.owner_id, _outdated_filter()
            )
        )
        or 0
    ) > 0


def _pending(session: Session, actor: Actor, index: Index) -> list[EmailSummaryRow]:
    rows = session.scalars(
        select(EmailSummaryRow).where(
            EmailSummaryRow.owner_id == actor.owner_id,
            EmailSummaryRow.status == SummaryStatus.pending.value,
        )
    ).all()
    return [r for r in rows if r.item_id in index]


def _due(session: Session, actor: Actor, index: Index, now: datetime) -> list[str]:
    """Pending summary ids that may run now, newest mail first."""
    due = {
        r.item_id: r.id
        for r in _pending(session, actor, index)
        if r.next_try_at is None or r.next_try_at <= now
    }
    return [due[item_id] for item_id in _order(list(due), index)]


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
        index = prepare(session, actor, now)
        due = _due(session, actor, index, now)
        outdated = _has_outdated(session, actor)
    if not due and not outdated:
        return False
    try:
        client = models.open_client(engine, actor, store, provider, model, budget, tick)
    except models.ModelUnavailable as exc:
        if exc.reason != "no_key":  # e.g. an unpriced model: a configuration mistake
            logger.warning("email summaries cannot run: %s", exc.reason)
        return False  # mail stays pending, nothing burnt
    if outdated:
        with Session(engine) as session:
            _redo_outdated(session, actor)
            due = _due(session, actor, index, now)
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
            item = integrations.items_by_id(session, actor, [row.item_id]).get(row.item_id)
            if item is None:  # the mail was deleted meanwhile
                handled += 1
                continue
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
            _record_failure(engine, summary_id, exc, tick(), prompt.version)
            handled += 1
            continue
        handled += 1
        with Session(engine) as session:
            row = session.get(EmailSummaryRow, summary_id)
            if row is None:  # the mail was deleted during the call
                continue
            row.status = SummaryStatus.ok.value
            row.gist = out.title
            row.points = out.points
            row.low_value = out.low_value
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
    engine: Engine, summary_id: str, exc: models.ModelFailed, now: datetime, version: int
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
            # Records which prompt failed, so only a newer prompt retries it (no loop).
            row.prompt_version = version
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
    index: Index,
) -> SummaryBlock:
    if not models.has_key(session, actor):
        return SummaryBlock.no_key
    if not pending:
        return SummaryBlock.none  # an old error does not matter while nothing waits
    last = models.last_error(session, actor)
    if last:
        return SummaryBlock(last)
    remaining = models.remaining_micro_usd(session, actor, now, budget)
    # Only the mail the next run would take: estimating thousands on every page load
    # would be slow, and the run itself stops at the first one over budget.
    upcoming = _order([r.item_id for r in pending], index)[:PER_RUN]
    for item in integrations.items_by_id(session, actor, upcoming).values():
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
    index: Index = {i: received for i, received, _changed in _mail_index(session, actor)}
    pending = _pending(session, actor, index)
    blocked = _blocked(session, actor, now, budget, vendor, model, prompt, pending, index)
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
