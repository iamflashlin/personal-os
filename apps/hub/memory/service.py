"""Second brain v0: memories with provenance, correction, expiry and text search.

Search: terms of 3+ characters go through the FTS5 `trigram` index (substring match in
any language, ranked by bm25); shorter terms, such as most two-character Chinese words,
fall back to a substring scan, because a trigram index cannot match them (ADR 0013).
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.base import UTCDateTime
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.memory.models import MemoryRow
from packages.contracts.memory import (
    Memory,
    MemoryConfirm,
    MemoryCreate,
    MemoryHit,
    MemoryUpdate,
    Provenance,
    Sensitivity,
)

ENTITY = "memory"
FTS_MIN_TERM = 3


def _read(row: MemoryRow) -> Memory:
    return Memory.model_validate(row, from_attributes=True)


def _get_row(session: Session, actor: Actor, memory_id: str) -> MemoryRow:
    row = session.get(MemoryRow, memory_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"memory {memory_id} not found")
    return row


def _hidden(body: str) -> dict[str, Any]:
    return {"length": len(body), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def _audit_view(values: dict[str, Any], *, sensitive: bool) -> dict[str, Any]:
    """The audit copy of a payload: a private or secret body becomes its length and hash."""
    if sensitive and isinstance(values.get("body"), str):
        return {**values, "body": _hidden(values["body"])}
    return values


def _check(data: dict[str, Any]) -> None:
    if data.get("provenance") == Provenance.verified:
        raise Invalid("provenance 'verified' needs Evidence and cannot be set through the API")
    expires_at = data.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        raise Invalid("expires_at must include a timezone, e.g. 2026-12-01T00:00:00Z")


def create(session: Session, actor: Actor, payload: MemoryCreate) -> Memory:
    data = payload.model_dump()
    sensitive = payload.sensitivity != Sensitivity.normal

    def op() -> audit.Outcome[Memory]:
        _check(data)
        row = MemoryRow(owner_id=actor.owner_id, source=actor.source, **data)
        session.add(row)
        session.flush()
        return audit.Outcome(row.id, _read(row))

    detail = {"payload": _audit_view(payload.model_dump(mode="json"), sensitive=sensitive)}
    return audit.audited(session, actor, ENTITY, "create", None, detail, op)


def get(session: Session, actor: Actor, memory_id: str) -> Memory:
    return _read(_get_row(session, actor, memory_id))


def list_all(session: Session, actor: Actor, include_expired: bool = False) -> list[Memory]:
    query = select(MemoryRow).where(MemoryRow.owner_id == actor.owner_id)
    if not include_expired:
        now = datetime.now(UTC)
        query = query.where((MemoryRow.expires_at.is_(None)) | (MemoryRow.expires_at > now))
    rows = session.scalars(query.order_by(MemoryRow.created_at, MemoryRow.id)).all()
    return [_read(r) for r in rows]


def _changes_detail(
    session: Session, actor: Actor, memory_id: str, patch: MemoryUpdate
) -> dict[str, Any]:
    current = session.get(MemoryRow, memory_id)
    old = current.sensitivity if current is not None else Sensitivity.secret
    new = patch.sensitivity or old
    # Hide the body if it is sensitive before or after the change.
    sensitive = old != Sensitivity.normal or new != Sensitivity.normal
    changes = patch.model_dump(mode="json", exclude_unset=True)
    return {"changes": _audit_view(changes, sensitive=sensitive)}


def update(session: Session, actor: Actor, memory_id: str, patch: MemoryUpdate) -> Memory:
    changes = patch.model_dump(exclude_unset=True, exclude={"version"})

    def op() -> audit.Outcome[Memory]:
        row = _get_row(session, actor, memory_id)
        if row.version != patch.version:
            raise Conflict(f"version is {row.version}, request was based on {patch.version}")
        current = MemoryCreate.model_validate(row, from_attributes=True).model_dump()
        try:
            merged = MemoryCreate.model_validate({**current, **changes}).model_dump()
        except ValidationError as exc:
            # Messages only: the rejected input could be a sensitive body.
            reasons = "; ".join(e["msg"] for e in exc.errors(include_input=False))
            raise Invalid(f"invalid change: {reasons}") from exc
        _check({"provenance": changes.get("provenance"), "expires_at": merged["expires_at"]})
        for name, value in merged.items():
            setattr(row, name, value)
        session.flush()
        return audit.Outcome(row.id, _read(row))

    detail = _changes_detail(session, actor, memory_id, patch)
    return audit.audited(session, actor, ENTITY, "update", memory_id, detail, op)


def confirm(session: Session, actor: Actor, memory_id: str, request: MemoryConfirm) -> Memory:
    """The user says this memory is right: provenance user_confirmed, confidence 1.0."""

    def op() -> audit.Outcome[Memory]:
        row = _get_row(session, actor, memory_id)
        if row.version != request.version:
            raise Conflict(f"version is {row.version}, request was based on {request.version}")
        if row.provenance == Provenance.verified:
            raise Conflict("a verified memory is already backed by evidence")
        row.provenance = Provenance.user_confirmed
        row.confidence = 1.0
        session.flush()
        return audit.Outcome(row.id, _read(row))

    detail = {"request": request.model_dump(mode="json")}
    return audit.audited(session, actor, ENTITY, "confirm", memory_id, detail, op)


def delete(session: Session, actor: Actor, memory_id: str) -> None:
    def op() -> audit.Outcome[None]:
        row = _get_row(session, actor, memory_id)
        session.delete(row)
        session.flush()
        return audit.Outcome(memory_id, None)

    audit.audited(session, actor, ENTITY, "delete", memory_id, {}, op)


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(
    session: Session,
    actor: Actor,
    q: str,
    *,
    include_expired: bool = False,
    include_secret: bool = False,
    limit: int = 20,
) -> list[MemoryHit]:
    terms = list(dict.fromkeys(t for t in q.split() if t))
    if not terms:
        raise Invalid("search needs at least one word")
    fts_terms = [t for t in terms if len(t) >= FTS_MIN_TERM]
    short_terms = [t for t in terms if len(t) < FTS_MIN_TERM]

    params: dict[str, Any] = {"owner": actor.owner_id, "limit": limit}
    where = ["m.owner_id = :owner"]
    if not include_expired:
        # `now` is bound through UTCDateTime, so it is stored-format-compatible by design.
        params["now"] = datetime.now(UTC)
        where.append("(m.expires_at IS NULL OR m.expires_at > :now)")
    if not include_secret:
        params["secret"] = Sensitivity.secret.value
        where.append("m.sensitivity != :secret")
    for i, term in enumerate(short_terms):
        params[f"like{i}"] = f"%{_like_escape(term)}%"
        where.append(f"m.body LIKE :like{i} ESCAPE '\\'")

    if fts_terms:
        params["match"] = " AND ".join('"' + t.replace('"', '""') + '"' for t in fts_terms)
        sql = (
            "SELECT m.id, bm25(memory_fts) AS score FROM memory_fts"
            " JOIN memory m ON m.id = memory_fts.memory_id"
            f" WHERE memory_fts MATCH :match AND {' AND '.join(where)}"
            " ORDER BY score, m.id LIMIT :limit"
        )
    else:
        sql = (
            f"SELECT m.id, NULL AS score FROM memory m WHERE {' AND '.join(where)}"
            " ORDER BY m.updated_at DESC, m.id LIMIT :limit"
        )
    statement = text(sql)
    if "now" in params:
        statement = statement.bindparams(bindparam("now", type_=UTCDateTime()))
    hits = session.execute(statement, params).all()
    rows = {
        r.id: r
        for r in session.scalars(select(MemoryRow).where(MemoryRow.id.in_([h[0] for h in hits])))
    }
    return [MemoryHit(memory=_read(rows[memory_id]), rank=score) for memory_id, score in hits]
