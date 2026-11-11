"""The 今日 view, computed from synced items and tasks (ADR 0023)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.briefing import service as briefing
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from packages.contracts.today import TodayView
from tests.hub.support import hub_client

LA = ZoneInfo("America/Los_Angeles")
# Wednesday 2026-11-11, 09:00 in California.
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=LA).astimezone(UTC)
OWNER = Actor(owner_id="local", source="test")


@pytest.fixture
def client(data_dir: Path) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False)) as c:
        yield c


@pytest.fixture
def session(client: TestClient) -> Iterator[Session]:
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        yield s


def source(session: Session, kind: str, name: str, owner: str = "local", error: str = "") -> str:
    row = IntegrationRow(
        owner_id=owner,
        source="test",
        kind=kind,
        name=name,
        credential_name="x",
        interval_s=900,
        config={},
        status="error" if error else "ok",
        last_error=error,
        cursor={},
    )
    session.add(row)
    session.flush()
    return row.id


def item(
    session: Session,
    integration_id: str,
    item_type: str,
    title: str,
    at: datetime | None,
    *,
    all_day: bool = False,
    owner: str = "local",
    **data: Any,
) -> None:
    session.add(
        SyncedItemRow(
            owner_id=owner,
            source="test",
            integration_id=integration_id,
            item_type=item_type,
            external_id=title,
            content_hash="h",
            title=title,
            body="",
            location="",
            url="https://deanza.example/a",
            starts_at=at,
            ends_at=None,
            all_day=all_day,
            data=data,
        )
    )
    session.flush()


def la(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=LA).astimezone(UTC)


def view(session: Session) -> TodayView:
    return briefing.today(session, OWNER, NOW, LA)


def titles(entries: list[Any]) -> list[str]:
    return [e.title for e in entries]


def test_an_empty_hub_gives_an_empty_day(session: Session) -> None:
    today = view(session)
    assert today.date == date(2026, 11, 11)
    assert today.headline == "今天没有截止、日程或未读邮件。"
    assert today.due_today == today.missing == today.mail == today.problems == []


def test_assignments_land_on_the_right_day_in_the_users_time_zone(session: Session) -> None:
    canvas = source(session, "canvas", "Canvas")
    # 23:59 in California on the 11th is already the 12th in UTC.
    item(session, canvas, "canvas_assignment", "Lab 3", la(11, 23, 59), course="CIS 22A")
    item(session, canvas, "canvas_assignment", "Essay", la(13, 23, 59), course="EWRT 1A")
    item(session, canvas, "canvas_assignment", "Far away", la(20, 23, 59))
    item(session, canvas, "canvas_assignment", "Quiz 2", la(9, 23, 59), missing=True)
    item(session, canvas, "canvas_assignment", "Lab 2", la(10, 23, 59), submission_state="graded")
    today = view(session)
    assert titles(today.due_today) == ["Lab 3"]
    assert today.due_today[0].note == "CIS 22A" and today.due_today[0].source == "Canvas"
    assert titles(today.due_soon) == ["Essay"]
    assert titles(today.missing) == ["Quiz 2"] and today.missing[0].badge == "缺交"
    assert "今天有 1 项截止" in today.headline and "1 项缺交或逾期" in today.headline


def test_old_missing_work_is_still_listed(session: Session) -> None:
    canvas = source(session, "canvas", "Canvas")
    item(
        session, canvas, "canvas_assignment", "Quiz 1", la(11, 9) - timedelta(days=40), missing=True
    )
    item(session, canvas, "canvas_assignment", "Old done", la(11, 9) - timedelta(days=40))
    assert titles(view(session).missing) == ["Quiz 1"]


def test_the_three_day_window_has_exact_edges_east_of_utc(session: Session) -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 11, 11, 9, 0, tzinfo=shanghai).astimezone(UTC)
    cal = source(session, "ics", "课表")

    def sh(day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 11, day, hour, minute, tzinfo=shanghai).astimezone(UTC)

    item(session, cal, "calendar_event", "Early today", sh(11, 0, 30))
    item(session, cal, "calendar_event", "Last minute", sh(14, 23, 59))
    item(session, cal, "calendar_event", "Too far", sh(15, 0, 0))
    item(
        session, cal, "calendar_event", "Holiday", datetime(2026, 11, 13, tzinfo=UTC), all_day=True
    )
    item(session, cal, "calendar_event", "Lunch on the 13th", sh(13, 12))
    today = briefing.today(session, OWNER, now, shanghai)
    assert titles(today.events) == ["Early today"]
    # The all-day item comes first on its day, not at 08:00 Shanghai time.
    assert titles(today.due_soon) == ["Holiday", "Lunch on the 13th", "Last minute"]


def test_graded_work_coming_up_is_badged(session: Session) -> None:
    canvas = source(session, "canvas", "Canvas")
    item(session, canvas, "canvas_assignment", "Essay", la(12, 20), submission_state="graded")
    (entry,) = view(session).due_soon
    assert entry.badge == "已评分"


def test_submitted_work_due_today_is_badged(session: Session) -> None:
    canvas = source(session, "canvas", "Canvas")
    item(session, canvas, "canvas_assignment", "Lab 3", la(11, 20), submission_state="submitted")
    (entry,) = view(session).due_today
    assert entry.badge == "已提交"


def test_all_day_events_stay_on_their_own_day(session: Session) -> None:
    cal = source(session, "ics", "课表")
    # All-day items are stored at UTC midnight; in California that is the evening before.
    item(
        session,
        cal,
        "calendar_event",
        "Veterans Day",
        datetime(2026, 11, 11, tzinfo=UTC),
        all_day=True,
    )
    item(session, cal, "calendar_event", "Office hours", la(11, 14))
    item(session, cal, "calendar_event", "Yesterday", la(10, 14))
    today = view(session)
    assert titles(today.events) == ["Veterans Day", "Office hours"]
    assert today.events[0].all_day is True


def test_only_unread_mail_from_the_last_day_is_listed_newest_first(session: Session) -> None:
    box = source(session, "email", "163 邮箱")
    item(session, box, "email_message", "Old unread", NOW - timedelta(hours=30), seen=False)
    item(session, box, "email_message", "Read", NOW - timedelta(hours=1), seen=True)
    for n in range(10):
        item(
            session,
            box,
            "email_message",
            f"New {n}",
            NOW - timedelta(minutes=10 + n),
            seen=False,
            from_name="Canvas 通知",
        )
    today = view(session)
    assert today.unread_mail == 10
    assert titles(today.mail) == [f"New {n}" for n in range(8)]
    assert today.mail[0].badge == "未读" and today.mail[0].note == "Canvas 通知"
    assert "10 封未读邮件" in today.headline


def test_announcements_from_the_last_two_days(session: Session) -> None:
    canvas = source(session, "canvas", "Canvas")
    item(session, canvas, "canvas_announcement", "Midterm moved", NOW - timedelta(hours=5))
    item(session, canvas, "canvas_announcement", "Welcome", NOW - timedelta(days=5))
    assert titles(view(session).announcements) == ["Midterm moved"]


def test_tasks_are_due_overdue_or_in_progress(client: TestClient, session: Session) -> None:
    def task(title: str, due: str | None, status: str = "todo") -> None:
        body: dict[str, Any] = {"title": title, "status": status}
        if due:
            body["due_date"] = due
        assert client.post("/tasks", json=body).status_code == 201

    task("Pay rent", "2026-11-11")
    task("Renew library book", "2026-11-08")
    task("Cancelled", "2026-11-11", "cancelled")
    task("Write notes", None, "in_progress")
    task("Waiting on TA", "2026-11-12", "blocked")
    today = view(session)
    assert titles(today.due_today) == ["Pay rent"] and today.due_today[0].source == "任务"
    assert titles(today.missing) == ["Renew library book"] and today.missing[0].badge == "逾期"
    assert titles(today.in_progress) == ["Write notes"]
    assert titles(today.due_soon) == ["Waiting on TA"]  # blocked work is still due
    assert "Cancelled" not in str(today.model_dump())


def test_a_failing_source_is_listed_as_a_problem(session: Session) -> None:
    source(session, "canvas", "Canvas", error="Canvas refused the token (HTTP 401)")
    today = view(session)
    (problem,) = today.problems
    assert problem.name == "Canvas" and "401" in problem.error
    assert today.headline.startswith("1 个来源同步失败")  # not an all-clear


def test_another_owners_data_never_appears(session: Session) -> None:
    theirs = source(session, "canvas", "Their Canvas", owner="someone-else", error="boom")
    item(session, theirs, "canvas_assignment", "Not mine", la(11, 20), owner="someone-else")
    today = view(session)
    assert today.due_today == [] and today.problems == []


def test_the_api_takes_the_browsers_time_zone(client: TestClient) -> None:
    answer = client.get("/today", params={"tz": "Asia/Shanghai"})
    assert answer.status_code == 200
    assert answer.json()["timezone"] == "Asia/Shanghai"
    for bad in ("Not/AZone", "America", "../etc", ""):
        status = client.get("/today", params={"tz": bad}).status_code
        assert status == (200 if bad == "" else 422), bad
    assert client.get("/today").status_code == 200  # falls back to this PC's zone
