# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""作业 (ADR 0044): what is missing, due soon and handed in, from synced Canvas
assignments; open an assignment's page on the PC; ask Canvas to sync now.

Submitted means Canvas recorded it. Nothing here writes or submits work."""

import re
from datetime import UTC, datetime, time, timedelta, tzinfo

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.actions import service as actions
from apps.hub.core.db import run_in_session
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.devices import service as devices
from apps.hub.gpa import service as gpa
from apps.hub.integrations import service as integrations
from apps.hub.schedule import service as schedule
from packages.contracts.actions import TITLE_MAX, ActionCreate, ActionName, OpenUrlParams
from packages.contracts.homework import (
    HomeworkBoard,
    HomeworkCheck,
    HomeworkItem,
    HomeworkOpened,
    HomeworkPlan,
    HomeworkSlot,
    HomeworkState,
    HomeworkWeek,
    HomeworkWeeks,
    PlannedTime,
)
from packages.contracts.integrations import SyncedItem
from packages.contracts.schedule import NewEvent

ITEM_TYPE = "canvas_assignment"
DONE_STATES = {"submitted", "graded", "pending_review"}  # as the schedule counts them
SOON = timedelta(hours=24)
WEEK = timedelta(days=7)
MISSING_LOOKBACK = timedelta(days=120)  # Canvas keeps old missing work; as 今日 does
PLAN_AHEAD = timedelta(days=14)  # a suggestion looks at most this far ahead
AHEAD = timedelta(days=60)  # early submissions of work due later still count as handed in


def _when(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _points(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _state(item: SyncedItem, now: datetime) -> HomeworkState | None:
    data = item.data
    if data.get("excused"):
        return None
    if data.get("submission_state") in DONE_STATES:
        submitted = _when(data.get("submitted_at"))
        return "submitted" if submitted is not None and submitted >= now - WEEK else None
    if data.get("missing"):
        return "missing"
    due = item.starts_at
    if due is None or due < now:
        return None  # past and not marked missing: handed in on paper, or not submittable
    if due <= now + SOON:
        return "soon"
    return "week" if due <= now + WEEK else None


def _marker(item_id: str) -> str:
    """Written into the planned event's notes; how the board finds it again (no new table)."""
    return f"homework:{item_id}"


MARKER = re.compile(r"^homework:([0-9A-HJKMNP-TV-Z]{26})$")  # a ULID, as _marker writes it


def _planned(session: Session, actor: Actor, now: datetime) -> dict[str, PlannedTime]:
    """Each homework's planned block that has not ended yet, read from the schedule (a
    moved or deleted event is reflected; a block that passed lets the user plan again).
    Only task blocks count, and only a marker line exactly as `_marker` writes it. The
    earliest block wins if the user copied it."""
    out: dict[str, PlannedTime] = {}
    for event in schedule.events(session, actor):
        if event.kind != "task" or event.ends_at <= now:
            continue
        for line in event.notes.splitlines():
            m = MARKER.match(line.strip())
            if m and m.group(1) not in out:
                out[m.group(1)] = PlannedTime(
                    event_id=event.id, starts_at=event.starts_at, ends_at=event.ends_at
                )
    return out


def _item(
    item: SyncedItem, state: HomeworkState, planned: PlannedTime | None = None
) -> HomeworkItem:
    data = item.data
    return HomeworkItem(
        id=item.id,
        title=item.title,
        course=str(data.get("course") or ""),
        course_code=str(data.get("course_code") or ""),
        due_at=item.starts_at,
        url=item.url,
        points=_points(data.get("points_possible")),
        state=state,
        submitted_at=_when(data.get("submitted_at")),
        late=bool(data.get("late")),
        planned=planned if state != "submitted" else None,
    )


def board(session: Session, actor: Actor, now: datetime | None = None) -> HomeworkBoard:
    now = now or datetime.now(UTC)
    sources = [s for s in integrations.list_all(session, actor) if s.kind == "canvas"]
    # Combined classes import the same work twice: a copy of handed-in work is not asked for
    # again, whether Canvas marks it missing or it is not due yet.
    copies = gpa.missing_copies(session, actor, now, include_open=True)
    groups: dict[HomeworkState, list[HomeworkItem]] = {
        "missing": [],
        "soon": [],
        "week": [],
        "submitted": [],
    }
    found = integrations.items_between(
        session, actor, now - MISSING_LOOKBACK, now + AHEAD, item_type=ITEM_TYPE
    )
    planned = _planned(session, actor, now)
    for item in found:
        state = _state(item, now)
        if state is None or (state != "submitted" and item.id in copies):
            continue
        groups[state].append(_item(item, state, planned.get(item.id)))
    groups["submitted"].sort(key=lambda h: h.submitted_at or now, reverse=True)
    synced = [s.last_success_at for s in sources if s.last_success_at is not None]
    return HomeworkBoard(
        generated_at=now,
        canvas=bool(sources),
        synced_at=max(synced) if synced else None,
        reminder=groups["soon"][0] if groups["soon"] else None,
        missing=groups["missing"],
        soon=groups["soon"],
        week=groups["week"],
        submitted=groups["submitted"],
    )


def weeks(
    session: Session,
    actor: Actor,
    count: int,
    zone: tzinfo,
    now: datetime | None = None,
) -> HomeworkWeeks:
    """The last `count` weeks of homework by due week (local Monday to Sunday): handed in
    on time, late, missing, still open. Excused work and combined-class copies are left
    out, as on the board; past work Canvas neither has a submission for nor marks missing
    (paper, in class) is not counted."""
    if not 1 <= count <= 12:
        raise Invalid("一次看 1 到 12 周")
    now = now or datetime.now(UTC)
    today = now.astimezone(zone).date()
    first = today - timedelta(days=today.weekday() + 7 * (count - 1))
    start = datetime.combine(first, time(), zone).astimezone(UTC)
    end = datetime.combine(first + timedelta(days=7 * count), time(), zone).astimezone(UTC)
    copies = gpa.missing_copies(session, actor, now, include_open=True)
    tally = [{"on_time": 0, "late": 0, "missing": 0, "open": 0} for _ in range(count)]
    for item in integrations.items_between(session, actor, start, end, item_type=ITEM_TYPE):
        data = item.data
        if item.starts_at is None or data.get("excused"):
            continue
        done = data.get("submission_state") in DONE_STATES
        handed = done and _when(data.get("submitted_at")) is not None
        if done and not handed:
            continue  # graded with no hand-in (paper, in class): not homework handed in
        if not handed and item.id in copies:
            continue
        if handed:
            kind = "late" if data.get("late") else "on_time"
        elif data.get("missing"):
            kind = "missing"
        elif item.starts_at >= now:
            kind = "open"
        else:
            continue
        index = (item.starts_at.astimezone(zone).date() - first).days // 7
        if 0 <= index < count:
            tally[index][kind] += 1
    return HomeworkWeeks(
        weeks=[HomeworkWeek(start=first + timedelta(days=7 * i), **t) for i, t in enumerate(tally)]
    )


def _assignment(session: Session, actor: Actor, item_id: str) -> SyncedItem:
    found = integrations.items_by_id(session, actor, [item_id]).get(item_id)
    if found is None or found.item_type != ITEM_TYPE:
        raise NotFound("没有这份作业")
    return found


def _payload(item: SyncedItem) -> ActionCreate:
    # The URL comes from the synced item, never from the browser (ADR 0044).
    try:
        params = OpenUrlParams.model_validate(
            {"url": item.url, "expect_title_contains": item.title.strip()[:TITLE_MAX]}
        )
    except ValidationError as exc:  # Canvas gave no page link (or no name to check it by)
        raise Invalid("这份作业没有可打开的 Canvas 链接") from exc
    return ActionCreate(name=ActionName.open_url, params=params.model_dump(mode="json"))


def _open_homework(session: Session, actor: Actor, item_id: str, now: datetime) -> SyncedItem:
    item = _assignment(session, actor, item_id)
    if _state(item, now) not in ("missing", "soon", "week"):
        raise Conflict("这份作业已经交了，或者不在这周要交的里面")
    return item


def suggest(
    session: Session,
    actor: Actor,
    item_id: str,
    minutes: int,
    zone: tzinfo,
    zone_name: str,
    now: datetime | None = None,
) -> HomeworkSlot:
    """The earliest free slot of `minutes` that ends before the homework is due (missing
    work: within the next week). Free time is the schedule's (ADR 0038): inside the day
    window, not blocked by classes or other events."""
    now = now or datetime.now(UTC)
    item = _open_homework(session, actor, item_id, now)
    due = item.starts_at
    # Open work is due within a week (and missing work gets the next week), so the cap is
    # only a safety bound on how far the agenda is read.
    end = min(due if due is not None and due > now else now + WEEK, now + PLAN_AHEAD)
    length = timedelta(minutes=minutes)
    found = schedule.agenda(session, actor, now, end, zone, zone_name, now=now)
    for free in found.free:
        start = _round_up(free.starts_at)
        if start + length <= free.ends_at:
            return HomeworkSlot(starts_at=start, ends_at=start + length, reason="")
    when = "截止前" if due is not None and due > now else "这周"
    return HomeworkSlot(
        starts_at=None, ends_at=None, reason=f"{when}没有连续 {minutes} 分钟的空闲时间"
    )


def _round_up(at: datetime) -> datetime:
    """To the next quarter hour, so the block reads 19:15, not 19:07."""
    at = at.replace(second=0, microsecond=0)
    return at + timedelta(minutes=(-at.minute) % 15)


def plan(
    session: Session,
    actor: Actor,
    item_id: str,
    body: HomeworkPlan,
    zone_name: str,
    now: datetime | None = None,
) -> tuple[PlannedTime, bool]:
    """Put the homework on the schedule as a task block. One block per homework: planning
    it again returns the block already there. Returns (block, created)."""
    now = now or datetime.now(UTC)
    item = _open_homework(session, actor, item_id, now)
    seen = _planned(session, actor, now).get(item.id)
    if seen is not None:
        return seen, False
    if body.starts_at < now - timedelta(minutes=5):
        raise Invalid("这个时间已经过去了")
    title = f"写作业：{item.title.strip()}"[:200]
    notes = "\n".join(line for line in (item.url, _marker(item.id)) if line)
    event = schedule.create(
        session,
        actor,
        NewEvent(
            title=title,
            kind="task",
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            notes=notes,
        ),
        zone_name,
    )
    return PlannedTime(event_id=event.id, starts_at=event.starts_at, ends_at=event.ends_at), True


def action_key(key: str) -> str:
    return f"homework:{key}"


async def open_page(
    engine: Engine, links: devices.AgentLinks, actor: Actor, item_id: str, key: str
) -> HomeworkOpened:
    """Open the assignment's Canvas page on the PC, at most once per key."""
    item = await run_in_session(engine, lambda s: _assignment(s, actor, item_id))
    done = await actions.dispatch(engine, links, actor, action_key(key), _payload(item))
    return HomeworkOpened(action=done.run, replayed=done.request is None)


def check(session: Session, actor: Actor, now: datetime | None = None) -> HomeworkCheck:
    """Ask each Canvas source to sync now, so a fresh submission shows up."""
    now = now or datetime.now(UTC)
    sources = [s for s in integrations.list_all(session, actor) if s.kind == "canvas"]
    if not sources:
        raise Conflict("还没有连接 Canvas")
    return HomeworkCheck(
        job_ids=[integrations.request_sync(session, actor, s.id, now) for s in sources]
    )


__all__ = ["action_key", "board", "check", "open_page", "plan", "suggest", "weeks"]
