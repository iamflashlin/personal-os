"""Outside sources: accounts, background sync through jobs, idempotent items (ADR 0019).

A sync is a job (at least once). It may run again after a crash, so storing what a source
returned is an upsert keyed by (integration, item type, external id).
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Invalid, NotFound
from apps.hub.credentials import service as credentials
from apps.hub.integrations.connectors import Batch, Connector, ItemIn, SyncError
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from apps.hub.integrations.registry import CONNECTORS, check_config
from apps.hub.jobs import service as jobs
from packages.contracts.integrations import (
    Integration,
    IntegrationCreate,
    IntegrationKind,
    IntegrationStatus,
    SyncedItem,
)

ENTITY = "integration"
SYNC_JOB = "integrations.sync"
MAX_ERROR = 1000


def _count(session: Session, integration_id: str) -> int:
    return (
        session.scalar(select(func.count()).where(SyncedItemRow.integration_id == integration_id))
        or 0
    )


def _read(session: Session, row: IntegrationRow) -> Integration:
    data = {c.key: getattr(row, c.key) for c in IntegrationRow.__table__.columns}
    return Integration.model_validate({**data, "item_count": _count(session, row.id)})


def _get_row(session: Session, actor: Actor, integration_id: str) -> IntegrationRow:
    row = session.get(IntegrationRow, integration_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"integration {integration_id} not found")
    return row


def schedule_kind(integration_id: str) -> str:
    """Each integration has its own schedule; `integrations.sync` handles them all."""
    return f"{SYNC_JOB}:{integration_id}"


def create(
    session: Session, actor: Actor, payload: IntegrationCreate, now: datetime
) -> Integration:
    """Create it and its sync schedule; the first sync is due at once."""

    def op() -> audit.Outcome[Integration]:
        try:
            config = check_config(payload.kind, payload.config)
        except ValueError as exc:
            raise Invalid(str(exc)) from None
        names = {c.name for c in credentials.list_all(session, actor)}
        if payload.credential_name not in names:
            raise Invalid(f"credential {payload.credential_name} is not set; PUT it first")
        row = IntegrationRow(
            owner_id=actor.owner_id,
            source=actor.source,
            kind=payload.kind,
            name=payload.name,
            credential_name=payload.credential_name,
            interval_s=payload.interval_s,
            config=config,
            status=IntegrationStatus.never_synced,
            last_error="",
            cursor={},
        )
        session.add(row)
        session.flush()
        return audit.Outcome(row.id, _read(session, row))

    detail = payload.model_dump(mode="json")
    created = audit.audited(session, actor, ENTITY, "create", None, detail, op)
    jobs.ensure_schedule(
        session,
        actor,
        schedule_kind(created.id),
        created.interval_s,
        {"integration_id": created.id},
        now=now,
    )
    return created


def get(session: Session, actor: Actor, integration_id: str) -> Integration:
    return _read(session, _get_row(session, actor, integration_id))


def list_all(session: Session, actor: Actor) -> list[Integration]:
    rows = session.scalars(
        select(IntegrationRow)
        .where(IntegrationRow.owner_id == actor.owner_id)
        .order_by(IntegrationRow.created_at)
    )
    return [_read(session, r) for r in rows]


def delete(session: Session, actor: Actor, integration_id: str) -> None:
    """Remove the integration and everything synced from it. Its credential stays."""

    def op() -> audit.Outcome[None]:
        row = _get_row(session, actor, integration_id)
        removed = _count(session, row.id)
        session.delete(row)  # synced_item rows go with it (ON DELETE CASCADE)
        session.flush()
        return audit.Outcome(row.id, None, {"items_removed": removed})

    audit.audited(session, actor, ENTITY, "delete", integration_id, {}, op)
    jobs.delete_schedule(session, actor, schedule_kind(integration_id))


def items(
    session: Session,
    actor: Actor,
    integration_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
    newest_first: bool = False,
    item_type: str | None = None,
) -> list[SyncedItem]:
    _get_row(session, actor, integration_id)
    query = select(SyncedItemRow).where(SyncedItemRow.integration_id == integration_id)
    if start is not None:
        query = query.where(SyncedItemRow.starts_at >= start)
    if end is not None:
        query = query.where(SyncedItemRow.starts_at < end)
    if item_type is not None:
        query = query.where(SyncedItemRow.item_type == item_type)
    when = SyncedItemRow.starts_at.desc() if newest_first else SyncedItemRow.starts_at
    rows = session.scalars(query.order_by(when, SyncedItemRow.external_id).limit(limit))
    return [SyncedItem.model_validate(r, from_attributes=True) for r in rows]


def items_between(
    session: Session,
    actor: Actor,
    start: datetime,
    end: datetime,
    item_type: str | None = None,
) -> list[SyncedItem]:
    """Every source's items that start in [start, end), for views across sources. Not
    capped: callers bound it by time, and a silent cut would drop real deadlines."""
    query = (
        select(SyncedItemRow)
        .join(IntegrationRow, IntegrationRow.id == SyncedItemRow.integration_id)
        .where(
            IntegrationRow.owner_id == actor.owner_id,
            SyncedItemRow.owner_id == actor.owner_id,
            SyncedItemRow.starts_at >= start,
            SyncedItemRow.starts_at < end,
        )
    )
    if item_type is not None:
        query = query.where(SyncedItemRow.item_type == item_type)
    rows = session.scalars(query.order_by(SyncedItemRow.starts_at, SyncedItemRow.id))
    return [SyncedItem.model_validate(r, from_attributes=True) for r in rows]


def item_index(
    session: Session, actor: Actor, item_type: str
) -> list[tuple[str, datetime | None, datetime]]:
    """(id, starts_at, updated_at) of every item of one type, without bodies: cheap enough
    to scan thousands of mails. Items without a start time are included."""
    query = (
        select(SyncedItemRow.id, SyncedItemRow.starts_at, SyncedItemRow.updated_at)
        .join(IntegrationRow, IntegrationRow.id == SyncedItemRow.integration_id)
        .where(
            IntegrationRow.owner_id == actor.owner_id,
            SyncedItemRow.owner_id == actor.owner_id,
            SyncedItemRow.item_type == item_type,
        )
    )
    return [(r[0], r[1], r[2]) for r in session.execute(query)]


ITEMS_PER_QUERY = 500  # well under SQLite's bound-parameter limit


@dataclass(frozen=True)
class ItemHead:
    """An item without its body: enough to search thousands of mails per question."""

    id: str
    received: datetime | None
    changed: datetime
    subject: str
    sender: str  # "Name <address>"


def item_heads(session: Session, actor: Actor, item_type: str) -> list[ItemHead]:
    query = (
        select(
            SyncedItemRow.id,
            SyncedItemRow.starts_at,
            SyncedItemRow.updated_at,
            SyncedItemRow.title,
            SyncedItemRow.data,
        )
        .join(IntegrationRow, IntegrationRow.id == SyncedItemRow.integration_id)
        .where(
            IntegrationRow.owner_id == actor.owner_id,
            SyncedItemRow.owner_id == actor.owner_id,
            SyncedItemRow.item_type == item_type,
        )
    )
    heads: list[ItemHead] = []
    for id_, starts_at, updated_at, title, data in session.execute(query):
        data = data or {}
        name, address = str(data.get("from_name") or ""), str(data.get("from_address") or "")
        sender = f"{name} <{address}>" if name and address else (name or address)
        heads.append(ItemHead(id_, starts_at, updated_at, title or "", sender))
    return heads


def items_by_id(session: Session, actor: Actor, ids: list[str]) -> dict[str, SyncedItem]:
    """Full items for these ids (another owner's ids are ignored)."""
    found: dict[str, SyncedItem] = {}
    for start in range(0, len(ids), ITEMS_PER_QUERY):
        chunk = ids[start : start + ITEMS_PER_QUERY]
        rows = session.scalars(
            select(SyncedItemRow)
            .join(IntegrationRow, IntegrationRow.id == SyncedItemRow.integration_id)
            .where(
                IntegrationRow.owner_id == actor.owner_id,
                SyncedItemRow.owner_id == actor.owner_id,
                SyncedItemRow.id.in_(chunk),
            )
        )
        for r in rows:
            found[r.id] = SyncedItem.model_validate(r, from_attributes=True)
    return found


def ensure_schedules(session: Session, actor: Actor, now: datetime) -> None:
    """Give every integration its schedule. Run at startup: if creating one failed after
    the integration was saved, this repairs it; a matching schedule writes nothing."""
    for row in session.scalars(
        select(IntegrationRow).where(IntegrationRow.owner_id == actor.owner_id)
    ).all():
        jobs.ensure_schedule(
            session,
            actor,
            schedule_kind(row.id),
            row.interval_s,
            {"integration_id": row.id},
            now=now,
        )


def request_sync(session: Session, actor: Actor, integration_id: str, now: datetime) -> str:
    """Queue a sync now; returns the job id. The worker runs one job at a time."""
    _get_row(session, actor, integration_id)
    job = jobs.enqueue(session, actor, SYNC_JOB, {"integration_id": integration_id}, now=now)
    return job.id


def _hash(item: ItemIn) -> str:
    fields = {
        "title": item.title,
        "body": item.body,
        "location": item.location,
        "url": item.url,
        "starts_at": item.starts_at.isoformat() if item.starts_at else None,
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
        "all_day": item.all_day,
        "data": item.data,
    }
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


MISSING_KEY = "missing_once"  # cursor entry: items absent from the last complete sync
MAX_MISSING = 2000
MAX_LOGGED_REMOVALS = 50


def _store(
    session: Session, actor: Actor, row: IntegrationRow, batch: Batch
) -> tuple[dict[str, int], dict[str, Any]]:
    """Upsert the batch. Returns the counts and extra audit detail (which items went)."""
    counts = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0}
    if batch.items is None:
        return counts, {}
    existing = {
        (i.item_type, i.external_id): i
        for i in session.scalars(
            select(SyncedItemRow).where(SyncedItemRow.integration_id == row.id)
        )
    }
    seen: set[tuple[str, str]] = set()
    for item in batch.items:
        key = (item.item_type, item.external_id)
        if key in seen:
            continue  # a feed listing the same id twice: the first one wins
        seen.add(key)
        digest = _hash(item)
        stored = existing.get(key)
        if stored is not None and stored.content_hash == digest:
            counts["unchanged"] += 1
            continue
        if stored is None:
            stored = SyncedItemRow(
                owner_id=actor.owner_id,
                source=f"integration:{row.kind}",
                integration_id=row.id,
                item_type=item.item_type,
                external_id=item.external_id,
            )
            session.add(stored)
            counts["added"] += 1
        else:
            counts["updated"] += 1
        stored.content_hash = digest
        stored.title = item.title
        stored.body = item.body
        stored.location = item.location
        stored.url = item.url
        stored.starts_at = item.starts_at
        stored.ends_at = item.ends_at
        stored.all_day = item.all_day
        stored.data = item.data
    # Patched fields (e.g. an email's read state) are left out of content_hash on purpose:
    # a connector must not also send them in the hashed item, or every sync would differ.
    for item_type, external_id, fields in batch.patches:
        stored = existing.get((item_type, external_id))
        if stored is not None and (item_type, external_id) not in seen:
            changed = {k: v for k, v in fields.items() if stored.data.get(k) != v}
            if changed:
                stored.data = {**stored.data, **changed}
                counts["updated"] += 1
    # Only a complete answer can say something is gone, and only twice in a row: one odd
    # answer (a course briefly missing from a list) must not delete anything. An empty
    # answer is more likely a glitch than everything vanishing, so it never counts.
    previous = set(row.cursor.get(MISSING_KEY, [])) if isinstance(row.cursor, dict) else set()
    if not (batch.complete and seen):
        return counts, {"pending_removal": len(previous)} if previous else {}
    missing = {f"{k[0]}:{k[1]}" for k in existing if k not in seen}
    removed: list[str] = []
    for key, stale in existing.items():
        label = f"{key[0]}:{key[1]}"
        if label in missing and label in previous:
            session.delete(stale)
            removed.append(label)
    counts["removed"] = len(removed)
    pending = sorted(missing - set(removed))
    batch.cursor[MISSING_KEY] = pending if len(pending) <= MAX_MISSING else []
    detail: dict[str, Any] = {"pending_removal": len(pending)}
    if removed:
        detail["removed_items"] = sorted(removed)[:MAX_LOGGED_REMOVALS]
        detail["removed_truncated"] = len(removed) > MAX_LOGGED_REMOVALS
    return counts, detail


def sync(
    engine: Engine,
    store: credentials.SecretStore,
    actor: Actor,
    integration_id: str,
    now: datetime,
    connectors: Mapping[IntegrationKind, Connector] = CONNECTORS,
) -> dict[str, int]:
    """Fetch and store one integration. On failure the status says why (redacted), and
    the error is raised again so the job is retried."""
    with Session(engine, expire_on_commit=False) as session:
        row = _get_row(session, actor, integration_id)
        kind, credential_name, cursor = IntegrationKind(row.kind), row.credential_name, row.cursor
        config = dict(row.config or {})
    try:
        with Session(engine) as session:
            secret = credentials.reveal(session, actor, store, credential_name)
        batch = connectors[kind].fetch(secret, cursor, config)
    except (SyncError, NotFound) as exc:
        _record_failure(engine, actor, integration_id, now, str(exc))
        raise
    except Exception as exc:
        # An unexpected error's text may quote the secret; keep only its type, here and
        # in what the job worker logs and stores.
        message = f"sync failed ({type(exc).__name__})"
        _record_failure(engine, actor, integration_id, now, message)
        raise SyncError(message) from None

    with Session(engine) as session:

        def op() -> audit.Outcome[dict[str, int]]:
            row = _get_row(session, actor, integration_id)
            counts, extra = _store(session, actor, row, batch)
            if not (batch.complete and batch.items):
                # Nothing was learnt about deletions: keep what was already pending.
                pending = row.cursor.get(MISSING_KEY) if isinstance(row.cursor, dict) else None
                if pending:
                    batch.cursor[MISSING_KEY] = pending
            row.cursor = batch.cursor
            row.status = IntegrationStatus.ok
            row.last_sync_at = now
            row.last_success_at = now
            row.last_error = ""
            session.flush()
            return audit.Outcome(row.id, counts, {**counts, **extra})

        return audit.audited(session, actor, ENTITY, "sync", integration_id, {}, op)


def _record_failure(
    engine: Engine, actor: Actor, integration_id: str, now: datetime, error: str
) -> None:
    message = audit.redact_text(error)[:MAX_ERROR]
    with Session(engine) as session:

        def op() -> audit.Outcome[None]:
            row = _get_row(session, actor, integration_id)
            row.status = IntegrationStatus.error
            row.last_sync_at = now
            row.last_error = message
            session.flush()
            return audit.Outcome(row.id, None, {"error": message}, "error")

        audit.audited(session, actor, ENTITY, "sync", integration_id, {}, op)


def run_sync_job(
    engine: Engine,
    store: credentials.SecretStore,
    actor: Actor,
    payload: Mapping[str, Any],
    now: datetime,
    connectors: Mapping[IntegrationKind, Connector] = CONNECTORS,
) -> None:
    integration_id = str(payload.get("integration_id", ""))
    with Session(engine) as session:
        if not session.scalar(
            select(func.count()).where(
                IntegrationRow.id == integration_id, IntegrationRow.owner_id == actor.owner_id
            )
        ):
            # Deleted after the job was queued, or its schedule outlived it: stop it.
            jobs.delete_schedule(session, actor, schedule_kind(integration_id))
            return
    sync(engine, store, actor, integration_id, now, connectors)
