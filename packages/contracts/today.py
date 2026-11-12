"""The 今日 page: one day's deadlines, missing work, events, mail and news (ADR 0023)."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from packages.contracts.summaries import Importance, SummaryStatus


class EntryKind(StrEnum):
    assignment = "assignment"
    task = "task"
    event = "event"
    mail = "mail"
    announcement = "announcement"


class EntrySummary(BaseModel):
    """The AI summary of a mail entry (ADR 0027)."""

    status: SummaryStatus
    gist: str = ""  # the AI title
    importance: Importance = Importance.normal
    low_value: bool = False
    action_needed: bool = False
    action: str = ""
    deadline_text: str = ""


class TodayEntry(BaseModel):
    kind: EntryKind
    title: str
    at: datetime | None
    all_day: bool = False
    source: str  # the integration's name, or "任务"
    note: str = ""  # course, sender, project
    url: str = ""
    badge: str = ""  # 缺交, 已提交, 未读, 逾期 …
    ref: str = ""  # task id or synced item id, for links back
    summary: EntrySummary | None = None  # mail only, once summarised or skipped


class SourceProblem(BaseModel):
    name: str
    error: str


class TodayView(BaseModel):
    date: date
    timezone: str
    generated_at: datetime
    headline: str
    due_today: list[TodayEntry]
    due_soon: list[TodayEntry]  # the next 3 days
    missing: list[TodayEntry]  # missing assignments and overdue tasks
    events: list[TodayEntry]
    unread_mail: int
    mail: list[TodayEntry]  # unread, last 24 h, newest first, at most 8
    announcements: list[TodayEntry]  # last 48 h
    in_progress: list[TodayEntry]
    problems: list[SourceProblem]  # sources whose last sync failed
    sources: int  # connected sources, so an empty day can say why it is empty
    # Mail from the last 7 days that the AI says needs action, read or not, deadline first.
    mail_actions: list[TodayEntry] = []
    ai_notice: str = ""  # why summaries are not running (budget, key), or ""
    low_value_mail: int = 0  # deprecated, always 0 (T-0028): low-value mail is listed
