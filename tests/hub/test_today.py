# ruff: noqa: RUF001  (Chinese test text uses full-width punctuation)
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
from apps.hub.triage import service as triage
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


# --- AI summaries on 今日 (T-0023, ADR 0027) ---------------------------------------------


def summarise(
    session: Session,
    title: str,
    status: str = "ok",
    *,
    action: str = "",
    deadline: date | None = None,
    owner: str = "local",
    low_value: bool = False,
) -> None:
    from sqlalchemy import select

    from apps.hub.summaries.models import EmailSummaryRow

    item_id = session.scalars(select(SyncedItemRow.id).where(SyncedItemRow.title == title)).one()
    session.add(
        EmailSummaryRow(
            owner_id=owner,
            source="test",
            version=1,
            item_id=item_id,
            item_hash="h",
            status=status,
            gist=f"摘要：{title}",
            action_needed=bool(action),
            action=action,
            deadline_text=str(deadline or ""),
            deadline_date=deadline,
            importance="normal",
            attempts=0,
            error="",
            model="fake",
            prompt_version=2,
            low_value=low_value,
        )
    )
    session.flush()


def test_mail_entries_carry_their_summary(session: Session) -> None:
    box = source(session, "email", "163")
    item(session, box, "email_message", "Lab 5", NOW - timedelta(hours=2), from_name="T")
    item(session, box, "email_message", "验证码", NOW - timedelta(hours=1))
    item(session, box, "email_message", "Waiting", NOW - timedelta(hours=3))
    summarise(session, "Lab 5", action="周五前提交")
    summarise(session, "验证码", "skipped_sensitive")
    summarise(session, "Waiting", "pending")
    by_title = {e.title: e.summary for e in view(session).mail}
    lab = by_title["摘要：Lab 5"]  # a summarised mail shows its AI title
    assert lab is not None and lab.gist == "摘要：Lab 5" and lab.action == "周五前提交"
    otp = by_title["验证码"]  # skipped: keeps its subject
    assert otp is not None and otp.status == "skipped_sensitive"
    assert by_title["Waiting"] is None  # pending shows nothing yet


def test_mail_actions_list_a_weeks_actionable_mail_deadline_first(session: Session) -> None:
    box = source(session, "email", "163")
    for n, (title, days, deadline) in enumerate(
        [
            ("Read and due soon", 5, date(2026, 11, 12)),
            ("Due later", 1, date(2026, 11, 20)),
            ("No deadline", 2, None),
            ("Too old", 8, date(2026, 11, 11)),
        ]
    ):
        item(session, box, "email_message", title, NOW - timedelta(days=days, minutes=n), seen=True)
        summarise(session, title, action="处理", deadline=deadline)
    item(session, box, "email_message", "Just news", NOW - timedelta(hours=1))
    summarise(session, "Just news")
    for n in range(12):
        item(session, box, "email_message", f"Extra {n}", NOW - timedelta(hours=5, minutes=n))
        summarise(session, f"Extra {n}", action="回复")
    actions = view(session).mail_actions
    shown = [t.removeprefix("摘要：") for t in titles(actions)]
    assert shown[:2] == ["Read and due soon", "Due later"]
    assert "Too old" not in shown and "Just news" not in shown
    assert len(actions) == 10
    assert all(a.summary is not None and a.summary.action_needed for a in actions)


def test_other_owners_summaries_never_appear(session: Session) -> None:
    mine = source(session, "email", "163")
    item(session, mine, "email_message", "Mine", NOW - timedelta(hours=1))
    summarise(session, "Mine", action="做", owner="other")  # a row that is not ours
    today = view(session)
    assert today.mail[0].summary is None
    assert today.mail_actions == []


def test_an_old_client_still_validates_the_view(session: Session) -> None:
    data = view(session).model_dump(mode="json")
    for new in ("mail_actions", "ai_notice"):
        data.pop(new)
    for entry in data["mail"]:
        entry.pop("summary", None)
    assert TodayView.model_validate(data).ai_notice == ""


def test_ai_notice_follows_the_summary_state(data_dir: Path) -> None:
    from apps.hub.credentials.service import MemorySecretStore

    store = MemorySecretStore()
    settings = Settings(
        data_dir=data_dir,
        jobs_enabled=False,
        model_provider="fake",
        ai_budget_usd=0.000001,  # pyright: ignore[reportArgumentType]
    )
    with hub_client(settings, secret_store=store) as c:
        assert c.get("/today").json()["ai_notice"] == ""  # no mail waiting: no banner
        with Session(c.app.state.engine) as s:  # type: ignore[attr-defined]
            box = source(s, "email", "163")
            item(s, box, "email_message", "Lab 6", datetime.now(UTC) - timedelta(hours=1))
            summarise(s, "Lab 6", "pending")
            s.commit()
        assert c.get("/today").json()["ai_notice"] == "还没有设置 DeepSeek key"
        c.put("/credentials/deepseek", json={"secret": "sk-test-today-0123456789"})
        assert c.get("/today").json()["ai_notice"] == "本月 AI 预算已用完"
        from apps.hub.models.models import ModelCallRow

        with Session(c.app.state.engine) as s:  # type: ignore[attr-defined]
            at = datetime.now(UTC)
            s.add(  # the newest call was refused: the key is wrong
                ModelCallRow(
                    owner_id="local",
                    source="test",
                    version=1,
                    created_at=at,
                    updated_at=at,
                    vendor="fake",
                    model="fake",
                    purpose="t",
                    prompt_name="p",
                    prompt_version=1,
                    prompt_sha="x",
                    status="error",
                    error_kind="auth",
                )
            )
            s.commit()
        assert c.get("/today").json()["ai_notice"] == "DeepSeek key 无效，请重新输入"


def test_mail_actions_without_a_deadline_are_newest_first(session: Session) -> None:
    box = source(session, "email", "163")
    for title, hours in [("Older", 30), ("Newest", 1), ("Middle", 10)]:
        item(session, box, "email_message", title, NOW - timedelta(hours=hours))
        summarise(session, title, action="回复")
    shown = [t.removeprefix("摘要：") for t in titles(view(session).mail_actions)]
    assert shown == ["Newest", "Middle", "Older"]


def test_low_value_mail_is_listed_in_time_order_like_any_other(session: Session) -> None:
    box = source(session, "email", "163")
    item(session, box, "email_message", "Lab 7", NOW - timedelta(hours=2))
    item(session, box, "email_message", "Sale 50% off", NOW - timedelta(hours=1))
    summarise(session, "Lab 7", action="提交")
    summarise(session, "Sale 50% off", action="买", low_value=True)
    today = view(session)
    assert titles(today.mail) == ["摘要：Sale 50% off", "摘要：Lab 7"]  # newest first
    assert today.mail[0].summary is not None and today.mail[0].summary.low_value
    assert today.unread_mail == 2 and today.low_value_mail == 0
    assert "Sale" not in " ".join(titles(today.mail_actions))  # never asked to act on ads


def test_an_old_prompt_gist_is_not_used_as_the_title(session: Session) -> None:
    from sqlalchemy import update

    from apps.hub.summaries.models import EmailSummaryRow

    box = source(session, "email", "163")
    item(session, box, "email_message", "Lab 8", NOW - timedelta(hours=1))
    summarise(session, "Lab 8")
    session.execute(update(EmailSummaryRow).values(prompt_version=1))
    session.flush()
    assert titles(view(session).mail) == ["Lab 8"]  # the v1 gist was a long sentence


def test_a_missing_copy_of_handed_in_work_is_not_missing(session: Session) -> None:
    """Combined classes import work twice; 今日 agrees with 成绩 that the copy is no gap."""
    canvas = source(session, "canvas", "Canvas")
    code = "F26 ENGL C1000 35Y"
    old = la(11, 9) - timedelta(days=40)
    item(
        session,
        canvas,
        "canvas_assignment",
        "Introduce Yourself",
        old,
        course_code=code,
        group_id=1,
        points_possible=2,
        score=2,
        submission_state="graded",
    )
    item(
        session,
        canvas,
        "canvas_assignment",
        " Introduce Yourself ",
        old,
        course_code=code,
        group_id=2,
        points_possible=2,
        missing=True,
    )
    item(
        session,
        canvas,
        "canvas_assignment",
        "Journal #9",
        old,
        course_code=code,
        group_id=1,
        points_possible=2,
        missing=True,
    )
    assert titles(view(session).missing) == ["Journal #9"]


# --- done mail leaves 今日 (T-0056) -------------------------------------------------------


def test_mail_whose_deadline_passed_needs_no_action(session: Session) -> None:
    box = source(session, "email", "163")
    for n, (title, deadline) in enumerate(
        [("Due yesterday", date(2026, 11, 10)), ("Due today", date(2026, 11, 11)), ("Open", None)]
    ):
        item(session, box, "email_message", title, NOW - timedelta(days=2, minutes=n), seen=True)
        summarise(session, title, action="交作业", deadline=deadline)
    shown = [t.removeprefix("摘要：") for t in titles(view(session).mail_actions)]
    assert shown == ["Due today", "Open"]  # today's deadline is still today


def test_mail_marked_handled_leaves_today(session: Session) -> None:
    box = source(session, "email", "163")
    for n, title in enumerate(["Done", "Still to do"]):
        item(session, box, "email_message", title, NOW - timedelta(hours=2, minutes=n))
        summarise(session, title, action="回复")
    before = view(session)
    assert before.unread_mail == 2 and len(before.mail_actions) == 2
    done = next(i for i in before.mail if i.title == "摘要：Done")
    triage.set_item(session, OWNER, done.ref, True)
    after = view(session)
    assert titles(after.mail_actions) == ["摘要：Still to do"]
    assert titles(after.mail) == ["摘要：Still to do"]
    assert after.unread_mail == 1 and "1 封未读邮件" in after.headline
    triage.set_item(session, OWNER, done.ref, False)  # back to 未处理: it returns
    assert len(view(session).mail_actions) == 2


def test_the_deadline_is_judged_on_the_users_own_date(session: Session) -> None:
    # 20:00 in LA on 11/11 is already 11/12 in UTC: a deadline of 11/11 is still today.
    box = source(session, "email", "163")
    item(session, box, "email_message", "Due tonight", NOW - timedelta(hours=2), seen=True)
    summarise(session, "Due tonight", action="交作业", deadline=date(2026, 11, 11))
    late = datetime(2026, 11, 11, 20, 0, tzinfo=LA).astimezone(UTC)
    assert late.date() == date(2026, 11, 12)
    actions = briefing.today(session, OWNER, late, LA).mail_actions
    assert titles(actions) == ["摘要：Due tonight"]


def test_mail_a_rule_handles_leaves_today_until_the_rule_is_off(session: Session) -> None:
    from apps.hub.triage.models import TriageRuleRow

    box = source(session, "email", "163")
    for n, title in enumerate(["Newsletter weekly", "Lab due"]):
        item(session, box, "email_message", title, NOW - timedelta(hours=2, minutes=n))
        summarise(session, title, action="看看")
    rule = TriageRuleRow(
        owner_id="local",
        source="test",
        version=1,
        name="newsletters",
        selector={"all_of": [{"kind": "text", "field": "subject", "value": "Newsletter"}]},
        enabled=True,
    )
    session.add(rule)
    session.flush()
    on = view(session)
    assert titles(on.mail_actions) == ["摘要：Lab due"] and on.unread_mail == 1
    triage.set_rule_enabled(session, OWNER, rule.id, False, date(2026, 11, 11))
    off = view(session)
    assert len(off.mail_actions) == 2 and off.unread_mail == 2


def test_another_owners_handled_mark_changes_nothing_here(session: Session) -> None:
    from apps.hub.triage.models import MailTriageStateRow

    box = source(session, "email", "163")
    item(session, box, "email_message", "Mine", NOW - timedelta(hours=1))
    summarise(session, "Mine", action="回复")
    mine = view(session).mail[0].ref
    session.add(
        MailTriageStateRow(
            owner_id="other", source="test", version=1, item_id=mine, state="handled"
        )
    )
    session.flush()
    assert len(view(session).mail_actions) == 1 and view(session).unread_mail == 1
