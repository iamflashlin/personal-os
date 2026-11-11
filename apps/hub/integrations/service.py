"""Outside sources: accounts, background sync through jobs, idempotent items (ADR 0019).

A sync is a job (at least once). It may run again after a crash, so storing what a source
returned is an upsert keyed by (integration, item type, external id).
"""

import hashlib
import json
from collections.abc import Mapping
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
) -> list[SyncedItem]:
    _get_row(session, actor, integration_id)
    query = select(SyncedItemRow).where(SyncedItemRow.integration_id == integration_id)
    if start is not None:
        query = query.where(SyncedItemRow.starts_at >= start)
    if end is not None:
        query = query.where(SyncedItemRow.starts_at < end)
    rows = session.scalars(
        query.order_by(SyncedItemRow.starts_at, SyncedItemRow.external_id).limit(limit)
    )
    return [SyncedItem.model_validate(r, from_attributes=True) for r in rows]


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


def _store(session: Session, actor: Actor, row: IntegrationRow, batch: Batch) -> dict[str, int]:
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    if batch.items is None:
        return counts
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
    return counts


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
            counts = _store(session, actor, row, batch)
            row.cursor = batch.cursor
            row.status = IntegrationStatus.ok
            row.last_sync_at = now
            row.last_success_at = now
            row.last_error = ""
            session.flush()
            return audit.Outcome(row.id, counts, dict(counts))

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
