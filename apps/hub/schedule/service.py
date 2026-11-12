# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""The schedule (ADR 0038): the user's own events plus synced calendar events and Canvas
deadlines, merged into one agenda with conflicts and free time. Planning (an AI placing
task blocks) comes later and will write events here the same way the user does."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.integrations import service as integrations
from apps.hub.schedule.models import ScheduleEventRow
from packages.contracts.schedule import (
    MAX_SPAN_DAYS,
    Agenda,
    AgendaEntry,
    EventFields,
    EventPatch,
    FreeSlot,
    NewEvent,
    ScheduleEvent,
)

DAY_WINDOW = (8, 22)  # local hours in which free time is looked for
LOOKBACK_DAYS = 14  # calendar events longer than this that started earlier are not shown
MIN_FREE_MINUTES = 30
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DONE_STATES = {"submitted", "graded", "pending_review"}


def _read(row: ScheduleEventRow) -> ScheduleEvent:
    return ScheduleEvent(
        id=row.id,
        title=row.title,
        kind=row.kind,  # type: ignore[arg-type]
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        all_day=row.all_day,
        location=row.location,
        notes=row.notes,
        repeat_days=list(row.repeat_days or []),
        repeat_until=row.repeat_until,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


def _apply(row: ScheduleEventRow, f: EventFields, zone_name: str) -> None:
    row.title, row.kind = f.title.strip(), f.kind
    row.starts_at, row.ends_at, row.all_day = f.starts_at, f.ends_at, f.all_day
    row.location, row.notes = f.location, f.notes
    row.repeat_days = [d for d in DAYS if d in f.repeat_days]
    row.repeat_until = f.repeat_until
    if zone_name or not row.time_zone:  # an edit without a zone keeps the entered one
        row.time_zone = zone_name


def _check_until(f: EventFields, zone_name: str) -> None:
    """repeat_until is a local date in the zone the event is entered in (an evening class
    is already the next day in UTC), so it is checked here, not in the contract."""
    if f.repeat_until is None:
        return
    first = f.starts_at.astimezone(_zone(zone_name, f.starts_at.tzinfo or UTC)).date()
    if f.repeat_until < first:
        raise Invalid("“直到”的日期早于第一次")


def create(session: Session, actor: Actor, new: NewEvent, zone_name: str) -> ScheduleEvent:
    _check_until(new, zone_name)

    def op() -> audit.Outcome[ScheduleEvent]:
        row = ScheduleEventRow(owner_id=actor.owner_id, source="manual", version=1)
        _apply(row, new, zone_name)
        session.add(row)
        session.flush()
        return audit.Outcome(
            row.id, _read(row), {"kind": row.kind, "repeats": bool(row.repeat_days)}
        )

    return audit.audited(session, actor, "schedule_event", "create", None, {}, op)


def _own(session: Session, actor: Actor, event_id: str) -> ScheduleEventRow:
    row = session.get(ScheduleEventRow, event_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound("没有这个日程")
    return row


def update(
    session: Session, actor: Actor, event_id: str, patch: EventPatch, zone_name: str
) -> ScheduleEvent:
    row = _own(session, actor, event_id)
    _check_until(patch.fields, zone_name or row.time_zone)
    if row.version != patch.version:
        raise Conflict("这个日程已经在别处改过了，刷新后再改")

    def op() -> audit.Outcome[ScheduleEvent]:
        _apply(row, patch.fields, zone_name)
        session.flush()
        return audit.Outcome(row.id, _read(row), {"kind": row.kind})

    return audit.audited(session, actor, "schedule_event", "update", event_id, {}, op)


def delete(session: Session, actor: Actor, event_id: str) -> None:
    row = _own(session, actor, event_id)

    def op() -> audit.Outcome[None]:
        session.delete(row)
        session.flush()
        return audit.Outcome(event_id, None, {})

    audit.audited(session, actor, "schedule_event", "delete", event_id, {}, op)


def _zone(name: str, fallback: tzinfo) -> tzinfo:
    try:
        return ZoneInfo(name) if name else fallback
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return fallback


def _occurrences(
    row: ScheduleEventRow, start: datetime, end: datetime, view_zone: tzinfo
) -> list[tuple[datetime, datetime]]:
    """UTC (start, end) pairs of this event inside [start, end). Weekly repeats keep the
    local wall-clock time of the zone the event was entered in (daylight saving safe)."""
    length = row.ends_at - row.starts_at
    if not row.repeat_days:
        return [(row.starts_at, row.ends_at)] if row.starts_at < end and row.ends_at > start else []
    zone = _zone(row.time_zone, view_zone)
    first = row.starts_at.astimezone(zone)
    days = {DAYS.index(d) for d in row.repeat_days if d in DAYS}
    day = max(first.date(), (start - length).astimezone(zone).date())
    last = end.astimezone(zone).date()
    if row.repeat_until is not None:
        last = min(last, row.repeat_until)
    out: list[tuple[datetime, datetime]] = []
    while day <= last:
        if day.weekday() in days:
            s = datetime.combine(day, first.timetz().replace(tzinfo=None), zone).astimezone(UTC)
            if s < end and s + length > start:
                out.append((s, s + length))
        day += timedelta(days=1)
    return out


def _mark_conflicts(entries: list[AgendaEntry]) -> None:
    timed = sorted(
        (e for e in entries if e.blocks and not e.all_day and e.ends_at is not None),
        key=lambda e: e.starts_at,
    )
    for i, a in enumerate(timed):
        for b in timed[i + 1 :]:
            if b.starts_at >= (a.ends_at or a.starts_at):
                break
            a.conflict = b.conflict = True


def _free(
    entries: list[AgendaEntry], start: datetime, end: datetime, zone: tzinfo
) -> list[FreeSlot]:
    busy = sorted(
        ((e.starts_at, e.ends_at) for e in entries if e.blocks and not e.all_day and e.ends_at),
        key=lambda x: x[0],
    )
    out: list[FreeSlot] = []
    day: date = start.astimezone(zone).date()
    while datetime.combine(day, time(0), zone) < end:
        lo = max(datetime.combine(day, time(DAY_WINDOW[0]), zone).astimezone(UTC), start)
        hi = min(datetime.combine(day, time(DAY_WINDOW[1]), zone).astimezone(UTC), end)
        cursor = lo
        for b_start, b_end in busy:
            if b_end is None or b_end <= cursor or b_start >= hi:
                continue
            if b_start > cursor:
                _slot(out, cursor, min(b_start, hi))
            cursor = max(cursor, b_end)
        if cursor < hi:
            _slot(out, cursor, hi)
        day += timedelta(days=1)
    return out


def _slot(out: list[FreeSlot], a: datetime, b: datetime) -> None:
    minutes = int((b - a).total_seconds() // 60)
    if minutes >= MIN_FREE_MINUTES:
        out.append(FreeSlot(starts_at=a, ends_at=b, minutes=minutes))


def agenda(
    session: Session,
    actor: Actor,
    start: datetime,
    end: datetime,
    zone: tzinfo,
    zone_name: str,
    now: datetime | None = None,
) -> Agenda:
    """`now`: free time is only listed from now on (past gaps are no use for planning)."""
    now = now or datetime.now(UTC)
    if end <= start:
        raise Invalid("结束时间要晚于开始时间")
    if end - start > timedelta(days=MAX_SPAN_DAYS):
        raise Invalid(f"一次最多查看 {MAX_SPAN_DAYS} 天")
    entries: list[AgendaEntry] = []
    rows = session.scalars(
        select(ScheduleEventRow).where(ScheduleEventRow.owner_id == actor.owner_id)
    )
    for row in rows:
        for s, e in _occurrences(row, start, end, zone):
            entries.append(
                AgendaEntry(
                    key=f"manual:{row.id}:{s.isoformat()}",
                    title=row.title,
                    kind=row.kind,
                    starts_at=s,
                    ends_at=e,
                    all_day=row.all_day,
                    location=row.location,
                    source="manual",
                    event_id=row.id,
                    repeats=bool(row.repeat_days),
                    url="",
                    blocks=not row.all_day,
                )
            )
    # Events that start before the window can still run into it (overnight, multi-day).
    lookback = start - timedelta(days=LOOKBACK_DAYS)
    for item in integrations.items_between(session, actor, lookback, end, "calendar_event"):
        if item.starts_at is None:
            continue
        if (item.ends_at or item.starts_at) <= start and item.starts_at < start:
            continue  # over before the window opens
        entries.append(
            AgendaEntry(
                key=f"calendar:{item.id}",
                title=item.title,
                kind="calendar",
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                all_day=item.all_day,
                location=item.location,
                source="calendar",
                event_id=None,
                url=item.url,
                blocks=not item.all_day,
            )
        )
    for item in integrations.items_between(session, actor, start, end, "canvas_assignment"):
        data = item.data
        if (
            item.starts_at is None
            or data.get("excused")
            or data.get("submission_state") in DONE_STATES
        ):
            continue  # done work is not a deadline any more
        entries.append(
            AgendaEntry(
                key=f"canvas:{item.id}",
                title=item.title,  # the 截止 badge says what it is
                kind="deadline",
                starts_at=item.starts_at,
                ends_at=None,
                all_day=False,
                location=str(data.get("course") or ""),
                source="canvas",
                event_id=None,
                url=item.url,
                blocks=False,
            )
        )
    entries.sort(key=lambda e: (e.starts_at, e.title))
    _mark_conflicts(entries)
    return Agenda(
        start=start,
        end=end,
        time_zone=zone_name or str(zone),
        entries=entries,
        free=_free(entries, max(start, now), end, zone) if now < end else [],
        day_window=DAY_WINDOW,
    )


__all__ = ["agenda", "create", "delete", "update"]
