"""作业 (ADR 0044): what is missing, due soon and handed in, from synced Canvas
assignments; open an assignment's page on the PC; ask Canvas to sync now.

Submitted means Canvas recorded it. Nothing here writes or submits work."""

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.actions import service as actions
from apps.hub.core.db import run_in_session
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.devices import service as devices
from apps.hub.gpa import service as gpa
from apps.hub.integrations import service as integrations
from packages.contracts.actions import TITLE_MAX, ActionCreate, ActionName, OpenUrlParams
from packages.contracts.homework import (
    HomeworkBoard,
    HomeworkCheck,
    HomeworkItem,
    HomeworkOpened,
    HomeworkState,
)
from packages.contracts.integrations import SyncedItem

ITEM_TYPE = "canvas_assignment"
DONE_STATES = {"submitted", "graded", "pending_review"}  # as the schedule counts them
SOON = timedelta(hours=24)
WEEK = timedelta(days=7)
MISSING_LOOKBACK = timedelta(days=120)  # Canvas keeps old missing work; as 今日 does
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


def _item(item: SyncedItem, state: HomeworkState) -> HomeworkItem:
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
    for item in found:
        state = _state(item, now)
        if state is None or (state != "submitted" and item.id in copies):
            continue
        groups[state].append(_item(item, state))
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


__all__ = ["action_key", "board", "check", "open_page"]
