# ruff: noqa: RUF001  (Chinese UI text uses full-width punctuation on purpose)
"""The 今日 page, computed from tasks and synced items (ADR 0023). Read-only."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.gpa import service as gpa
from apps.hub.integrations import service as integrations
from apps.hub.summaries import service as summaries
from apps.hub.tasks import service as tasks
from packages.contracts.integrations import IntegrationStatus, SyncedItem
from packages.contracts.summaries import EmailSummary, SummaryStatus
from packages.contracts.tasks import Task, TaskStatus
from packages.contracts.today import (
    EntryKind,
    EntrySummary,
    SourceProblem,
    TodayEntry,
    TodayView,
)

SOON_DAYS = 3
RECENT_DAYS = 2  # covers the 24 h mail and 48 h announcement windows from any time today
MISSING_DAYS = 120  # Canvas keeps old missing work actionable; look back a whole term
MAIL_HOURS = 24
NEWS_HOURS = 48
MAX_MAIL = 8
ACTION_DAYS = 7  # 需要处理的邮件: read or not, from the last week
MAX_ACTIONS = 10
OPEN = {TaskStatus.todo, TaskStatus.in_progress, TaskStatus.blocked}


def _local_date(at: datetime | None, all_day: bool, tz: tzinfo) -> date | None:
    """The calendar day for the user. All-day items are stored at UTC midnight of their
    day, so their day is the UTC date, not a shifted local one."""
    if at is None:
        return None
    return at.astimezone(UTC).date() if all_day else at.astimezone(tz).date()


def _since(item: SyncedItem, now: datetime, hours: int) -> bool:
    return item.starts_at is not None and item.starts_at >= now - timedelta(hours=hours)


def _web_link(url: str) -> str:
    return url if urlsplit(url).scheme.lower() in ("http", "https") else ""


def _entry(item: SyncedItem, source: str) -> TodayEntry:
    data: dict[str, Any] = item.data
    kind = {
        "canvas_assignment": EntryKind.assignment,
        "canvas_announcement": EntryKind.announcement,
        "email_message": EntryKind.mail,
    }.get(item.item_type, EntryKind.event)
    badge = ""
    if kind is EntryKind.assignment:
        if data.get("missing"):
            badge = "缺交"
        elif data.get("submission_state") == "graded":
            badge = "已评分"
        elif data.get("submission_state") in ("submitted", "pending_review"):
            badge = "已提交"
    if kind is EntryKind.mail and not data.get("seen"):
        badge = "未读"
    note = str(data.get("course") or data.get("from_name") or data.get("from_address") or "")
    return TodayEntry(
        kind=kind,
        title=item.title,
        at=item.starts_at,
        all_day=item.all_day,
        source=source,
        note=note,
        url=_web_link(item.url),
        badge=badge,
        ref=item.id,
    )


def _task_entry(task: Task, badge: str = "") -> TodayEntry:
    at = datetime.combine(task.due_date, time(), UTC) if task.due_date else None
    return TodayEntry(
        kind=EntryKind.task,
        title=task.title,
        at=at,
        all_day=task.due_date is not None,
        source="任务",
        badge=badge,
        ref=task.id,
    )


def _headline(view: dict[str, Any], problems: int) -> str:
    parts = []
    if view["due_today"]:
        parts.append(f"今天有 {len(view['due_today'])} 项截止")
    if view["missing"]:
        parts.append(f"{len(view['missing'])} 项缺交或逾期")
    if view["events"]:
        parts.append(f"{len(view['events'])} 个日程")
    if view["unread_mail"]:
        parts.append(f"{view['unread_mail']} 封未读邮件")
    text = "，".join(parts) + "。" if parts else "今天没有截止、日程或未读邮件。"
    if problems:
        # Without this, stale data from a broken source reads as an all-clear.
        text = f"{problems} 个来源同步失败，以下可能不完整。{text}"
    return text


def zone_name(tz: tzinfo, now: datetime) -> str:
    return str(getattr(tz, "key", "") or now.astimezone(tz).tzname() or "UTC")


def _summary(found: EmailSummary | None) -> EntrySummary | None:
    if found is None or found.status is SummaryStatus.pending:
        return None
    return EntrySummary(
        status=found.status,
        gist=found.gist,
        importance=found.importance,
        low_value=found.low_value,
        action_needed=found.action_needed,
        action=found.action,
        deadline_text=found.deadline_text,
    )


def _apply(entry: TodayEntry, found: EmailSummary | None) -> None:
    """Attach the summary; a summarised mail shows its AI title, not the subject."""
    entry.summary = _summary(found)
    if (
        found is not None
        and found.status is SummaryStatus.ok
        and found.gist
        and found.prompt_version >= summaries.TITLE_SINCE_VERSION  # v1 gists are long sentences
    ):
        entry.title = found.gist


def _mail_actions(
    session: Session, actor: Actor, now: datetime, names: dict[str, str]
) -> list[TodayEntry]:
    """Mail the AI says needs action: deadline first (soonest), then newest."""
    week = integrations.items_between(
        session,
        actor,
        now - timedelta(days=ACTION_DAYS),
        now + timedelta(days=1),
        item_type="email_message",
    )
    found = {
        s.item_id: s
        for s in summaries.summaries_for(session, actor, [i.id for i in week], limit=None)
    }
    picked: list[tuple[EmailSummary, TodayEntry]] = []
    for item in week:
        summary = found.get(item.id)
        if summary is None or summary.status is not SummaryStatus.ok or not summary.action_needed:
            continue
        if summary.low_value:
            continue
        entry = _entry(item, names.get(item.integration_id, ""))
        _apply(entry, summary)
        picked.append((summary, entry))
    latest = date.max
    oldest = datetime.min.replace(tzinfo=UTC)
    picked.sort(key=lambda p: p[1].at or oldest, reverse=True)  # newest first ...
    picked.sort(key=lambda p: p[0].deadline_date or latest)  # ... within the deadline order
    return [entry for _, entry in picked[:MAX_ACTIONS]]


def today(
    session: Session, actor: Actor, now: datetime, tz: tzinfo, ai_notice: str = ""
) -> TodayView:
    local_today = now.astimezone(tz).date()
    day_start = datetime.combine(local_today, time(), tz).astimezone(UTC)
    recent_start = day_start - timedelta(days=RECENT_DAYS)
    window_end = day_start + timedelta(days=SOON_DAYS + 1)
    soon_last = local_today + timedelta(days=SOON_DAYS)

    due_today: list[TodayEntry] = []
    due_soon: list[TodayEntry] = []
    missing: list[TodayEntry] = []
    events: list[TodayEntry] = []
    mail: list[TodayEntry] = []
    news: list[TodayEntry] = []
    unread = 0

    sources = integrations.list_all(session, actor)
    names = {s.id: s.name for s in sources}
    found = integrations.items_between(session, actor, recent_start, window_end)
    # Older assignments matter only when Canvas still marks them missing.
    older = integrations.items_between(
        session,
        actor,
        day_start - timedelta(days=MISSING_DAYS),
        recent_start,
        item_type="canvas_assignment",
    )
    copies = gpa.missing_copies(session, actor, now)
    for item in older + found:
        source = names.get(item.integration_id, "")
        day = _local_date(item.starts_at, item.all_day, tz)
        entry = _entry(item, source)
        if entry.kind is EntryKind.assignment:
            if item.id in copies:
                continue  # a copy of handed-in work (combined classes), as 成绩 says
            if item.data.get("missing"):
                missing.append(entry)
            elif day == local_today:
                due_today.append(entry)
            elif day is not None and local_today < day <= soon_last:
                due_soon.append(entry)
        elif entry.kind is EntryKind.event:
            if day == local_today:
                events.append(entry)
            elif day is not None and local_today < day <= soon_last:
                due_soon.append(entry)
        elif entry.kind is EntryKind.mail:
            if _since(item, now, MAIL_HOURS) and not item.data.get("seen"):
                unread += 1
                mail.append(entry)
        elif entry.kind is EntryKind.announcement and _since(item, now, NEWS_HOURS):
            news.append(entry)

    in_progress: list[TodayEntry] = []
    for task in tasks.list_all(session, actor, tasks.KINDS["task"]):
        if not isinstance(task, Task) or task.status not in OPEN:
            continue
        if task.due_date is not None and task.due_date < local_today:
            missing.append(_task_entry(task, "逾期"))
        elif task.due_date == local_today:
            due_today.append(_task_entry(task))
        elif task.due_date is not None and task.due_date <= soon_last:
            due_soon.append(_task_entry(task))
        if task.status is TaskStatus.in_progress:
            in_progress.append(_task_entry(task, "进行中"))

    def by_day(e: TodayEntry) -> tuple[date, bool, datetime]:
        """By the user's day, all-day items first within it, then by time."""
        latest = datetime.max.replace(tzinfo=UTC)
        day = _local_date(e.at, e.all_day, tz) or date.max
        return (day, not e.all_day, e.at or latest)

    def newest(e: TodayEntry) -> datetime:
        return e.at or datetime.min.replace(tzinfo=UTC)

    mail_found = {
        s.item_id: s
        for s in summaries.summaries_for(session, actor, [e.ref for e in mail], limit=None)
    }
    # Low-value mail is listed like any other, in time order (the user, 2026-11-11); it is
    # only marked 次要 by its summary.
    for entry in mail:
        _apply(entry, mail_found.get(entry.ref))

    view: dict[str, Any] = {
        "due_today": sorted(due_today, key=by_day),
        "due_soon": sorted(due_soon, key=by_day),
        "missing": sorted(missing, key=by_day),
        "events": sorted(events, key=by_day),
        "unread_mail": unread,
        "mail": sorted(mail, key=newest, reverse=True)[:MAX_MAIL],
        "announcements": sorted(news, key=newest, reverse=True),
        "in_progress": in_progress,
    }
    problems = [
        SourceProblem(name=s.name, error=s.last_error)
        for s in sources
        if s.status == IntegrationStatus.error
    ]
    return TodayView(
        date=local_today,
        timezone=zone_name(tz, now),
        generated_at=now,
        headline=_headline(view, len(problems)),
        problems=problems,
        sources=len(sources),
        mail_actions=_mail_actions(session, actor, now, names),
        low_value_mail=0,  # deprecated (T-0028), kept for older clients
        ai_notice=ai_notice,
        **view,
    )
