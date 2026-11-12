"""The 简报 (ADR 0039): outside information, today vs history, read/unread.

Sources (news feeds, club IG/Discord, the WeChat transfer group) are not connected yet;
items come in through `add` (by hand now, by connectors later), always keeping the
original text. Nothing here sends anything to a model."""

import hashlib
from datetime import UTC, datetime, time, tzinfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, NotFound
from apps.hub.digest.models import DigestItemRow
from packages.contracts.digest import DigestItem, DigestView, NewDigestItem

HISTORY_LIMIT = 300


def _key(new: NewDigestItem, published: datetime, zone: tzinfo) -> str:
    """One item once: the same link from the same source; without a link, the same title on
    the same day (a weekly "本周活动" post comes back under the same title)."""
    day = published.astimezone(zone).date().isoformat()  # the user's day, not UTC's
    basis = new.url.strip() or f"{day}|{new.title.strip().casefold()}"
    raw = f"{new.channel}|{new.source_name.strip().casefold()}|{basis}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read(row: DigestItemRow) -> DigestItem:
    return DigestItem(
        id=row.id,
        channel=row.channel,  # type: ignore[arg-type]
        source_name=row.source_name,
        title=row.title,
        summary=row.summary,
        raw_text=row.raw_text,
        url=row.url,
        topics=list(row.topics or []),
        published_at=row.published_at,
        happens_at=row.happens_at,
        important=row.important,
        read=row.read_at is not None,
        read_at=row.read_at,
        origin=row.source,
        created_at=row.created_at,
        version=row.version,
    )


def add(
    session: Session,
    actor: Actor,
    new: NewDigestItem,
    now: datetime,
    origin: str = "manual",
    zone: tzinfo = UTC,
) -> DigestItem:
    # A future publish time would keep an item in 今天 for days: clamp it to now.
    published = min(new.published_at or now, now)
    key = _key(new, published, zone)
    exists = session.scalar(
        select(DigestItemRow).where(
            DigestItemRow.owner_id == actor.owner_id, DigestItemRow.dedup_key == key
        )
    )
    if exists is not None:
        raise Conflict("这条已经在简报里了")

    def op() -> audit.Outcome[DigestItem]:
        row = DigestItemRow(
            owner_id=actor.owner_id,
            source=origin,
            version=1,
            channel=new.channel,
            source_name=new.source_name.strip(),
            title=new.title.strip(),
            summary=new.summary.strip(),
            raw_text=new.raw_text,
            url=new.url.strip(),
            topics=[t.strip() for t in new.topics if t.strip()],
            published_at=published,
            happens_at=new.happens_at,
            important=new.important,
            dedup_key=key,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            raise Conflict("这条已经在简报里了") from None
        return audit.Outcome(row.id, _read(row), {"channel": row.channel})

    return audit.audited(session, actor, "digest_item", "create", None, {}, op)


def set_read(session: Session, actor: Actor, item_id: str, read: bool, now: datetime) -> DigestItem:
    row = session.get(DigestItemRow, item_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound("没有这条简报")

    def op() -> audit.Outcome[DigestItem]:
        row.read_at = now if read else None
        session.flush()
        return audit.Outcome(row.id, _read(row), {"read": read})

    return audit.audited(session, actor, "digest_item", "read", item_id, {}, op)


def _day_start(now: datetime, zone: tzinfo) -> datetime:
    local = now.astimezone(zone)
    return datetime.combine(local.date(), time(0), zone).astimezone(UTC)


def read_all(
    session: Session,
    actor: Actor,
    view: str,
    now: datetime,
    zone: tzinfo,
    channel: str | None = None,
) -> int:
    """Mark read what the user sees: this view, and only the chosen channel if one is set."""
    start = _day_start(now, zone)
    query = select(DigestItemRow).where(
        DigestItemRow.owner_id == actor.owner_id, DigestItemRow.read_at.is_(None)
    )
    query = query.where(
        DigestItemRow.published_at >= start
        if view == "today"
        else DigestItemRow.published_at < start
    )
    if channel:
        query = query.where(DigestItemRow.channel == channel)
    rows = list(session.scalars(query))
    if not rows:
        return 0

    def op() -> audit.Outcome[int]:
        for r in rows:
            r.read_at = now
        session.flush()
        return audit.Outcome(None, len(rows), {"view": view, "count": len(rows)})

    return audit.audited(session, actor, "digest_item", "read_all", None, {}, op)


def view(
    session: Session,
    actor: Actor,
    which: str,
    now: datetime,
    zone: tzinfo,
    unread_only: bool = False,
    channel: str | None = None,
) -> DigestView:
    """Today = posted since local midnight; history = everything before, newest first."""
    start = _day_start(now, zone)
    rows = list(
        session.scalars(
            select(DigestItemRow)
            .where(DigestItemRow.owner_id == actor.owner_id)
            .order_by(DigestItemRow.published_at.desc(), DigestItemRow.id.desc())
        )
    )
    today = [r for r in rows if r.published_at >= start]
    history = [r for r in rows if r.published_at < start]
    chosen = today if which == "today" else history[:HISTORY_LIMIT]
    channels: dict[str, int] = {}
    for r in chosen:
        if r.read_at is None:
            channels[r.channel] = channels.get(r.channel, 0) + 1
    if channel:
        chosen = [r for r in chosen if r.channel == channel]
    if unread_only:
        chosen = [r for r in chosen if r.read_at is None]
    # Important and unread first inside today; history stays in time order.
    if which == "today":
        chosen.sort(key=lambda r: (r.read_at is not None, not r.important))
    return DigestView(
        view="today" if which == "today" else "history",
        items=[_read(r) for r in chosen],
        unread_today=sum(1 for r in today if r.read_at is None),
        unread_history=sum(1 for r in history if r.read_at is None),
        channels=channels,
    )


__all__ = ["add", "read_all", "set_read", "view"]
