# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""作业 (ADR 0044): submission state from Canvas, open the page on the PC, sync now."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.homework import service as homework
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from apps.hub.schedule import service as schedule
from packages.contracts.actions import ActionStatus
from packages.contracts.agent_protocol import ActionRequestMsg
from packages.contracts.homework import HomeworkPlan
from packages.contracts.schedule import NewEvent
from tests.hub.agent_support import connect, heartbeat, hello, pair, receive
from tests.hub.support import hub_client
from tests.hub.test_actions import answer
from tests.hub.test_gpa import canvas, item

NOW = datetime.now(UTC)
A = "canvas_assignment"


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        yield client, client.app.state.engine  # type: ignore[attr-defined]


def seed(engine: Engine) -> dict[str, str]:
    c = canvas(engine)
    course = {"course": "F26 ENGL C1000 Reading", "course_code": "ENGL C1000"}
    h = timedelta(hours=1)
    return {
        "missing": item(engine, c, A, "1:1", "Essay 1", NOW - 48 * h, missing=True, **course),
        "soon_late": item(engine, c, A, "1:2", "Journal 5", NOW + 20 * h, **course),
        "soon": item(engine, c, A, "1:3", "Journal 4", NOW + 3 * h, points_possible=10, **course),
        "week": item(engine, c, A, "1:4", "Essay 2", NOW + 72 * h, **course),
        "far": item(engine, c, A, "1:5", "Final paper", NOW + 30 * 24 * h, **course),
        "handed": item(
            engine,
            c,
            A,
            "1:6",
            "Journal 3",
            NOW + 5 * h,
            submission_state="submitted",
            submitted_at=iso(NOW - 2 * h),
            late=False,
            **course,
        ),
        "graded_old": item(
            engine,
            c,
            A,
            "1:7",
            "Journal 1",
            NOW - 20 * 24 * h,
            submission_state="graded",
            submitted_at=iso(NOW - 21 * 24 * h),
            **course,
        ),
        "late_handed": item(
            engine,
            c,
            A,
            "1:8",
            "Journal 2",
            NOW - 30 * h,
            submission_state="submitted",
            submitted_at=iso(NOW - 6 * h),
            late=True,
            **course,
        ),
        "excused": item(engine, c, A, "1:9", "Quiz", NOW + 2 * h, excused=True, **course),
        "paper": item(engine, c, A, "1:10", "In-class", NOW - 5 * h, **course),
        "module": item(engine, c, "canvas_module_item", "m:1", "Notes", NOW + h),
        "canvas": c,
    }


def titles(rows: list[dict[str, Any]]) -> list[str]:
    return [r["title"] for r in rows]


def test_the_board_groups_homework_by_what_needs_doing(hub) -> None:
    client, engine = hub
    seed(engine)
    r = client.get("/homework")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["canvas"] is True
    assert titles(b["missing"]) == ["Essay 1"]
    assert titles(b["soon"]) == ["Journal 4", "Journal 5"]  # nearest first
    assert titles(b["week"]) == ["Essay 2"]  # the final paper is a month away
    # newest submission first; Journal 1 was handed in three weeks ago
    assert titles(b["submitted"]) == ["Journal 3", "Journal 2"]
    assert b["submitted"][1]["late"] is True
    assert b["submitted"][0]["submitted_at"] is not None
    soon = b["soon"][0]
    assert soon["course_code"] == "ENGL C1000"
    assert soon["points"] == 10
    assert soon["url"] == "https://c/1:3"
    assert soon["state"] == "soon"
    # excused work, past work Canvas does not mark missing, and module items are left out
    every = [t for g in ("missing", "soon", "week", "submitted") for t in titles(b[g])]
    assert not {"Quiz", "In-class", "Notes", "Final paper", "Journal 1"} & set(every)


def test_the_reminder_is_the_nearest_unsubmitted_homework_due_within_a_day(hub) -> None:
    client, engine = hub
    seed(engine)
    assert client.get("/homework").json()["reminder"]["title"] == "Journal 4"


def test_no_reminder_when_nothing_is_due_within_a_day(hub) -> None:
    client, engine = hub
    c = canvas(engine)
    item(engine, c, A, "2:1", "Later", NOW + timedelta(days=3))
    b = client.get("/homework").json()
    assert b["reminder"] is None
    assert titles(b["week"]) == ["Later"]


def test_without_canvas_the_board_is_empty_and_says_so(hub) -> None:
    client, _ = hub
    b = client.get("/homework").json()
    assert b["canvas"] is False
    assert b["synced_at"] is None
    assert b["missing"] == b["soon"] == b["week"] == b["submitted"] == []


def test_open_without_an_agent_is_503_and_sends_nothing(hub) -> None:
    client, engine = hub
    ids = seed(engine)
    r = client.post(f"/homework/{ids['soon']}/open", headers={"Idempotency-Key": "k-1"})
    assert r.status_code == 503
    assert client.get("/actions").json() == []


def test_open_unknown_or_non_assignment_is_404(hub) -> None:
    client, engine = hub
    ids = seed(engine)
    for bad in ("nope", ids["module"], ids["canvas"], other_owners(engine)):
        r = client.post(f"/homework/{bad}/open", headers={"Idempotency-Key": f"k-{bad}"})
        assert r.status_code == 404, bad


def other_owners(engine: Engine) -> str:
    """Another owner's Canvas assignment, due soon."""
    with Session(engine) as s:
        source = IntegrationRow(
            owner_id="other",
            source="test",
            version=1,
            kind="canvas",
            name="Canvas",
            credential_name="x",
            interval_s=900,
            config={},
            status="ok",
            last_error="",
            cursor={},
        )
        s.add(source)
        s.flush()
        row = SyncedItemRow(
            owner_id="other",
            source="test",
            version=1,
            integration_id=source.id,
            item_type=A,
            external_id="9:9",
            content_hash="9:9",
            title="Not yours",
            body="",
            location="",
            url="https://c/9:9",
            starts_at=NOW + timedelta(hours=2),
            ends_at=None,
            all_day=False,
            data={},
        )
        s.add(row)
        s.commit()
        return row.id


def test_another_owners_homework_is_not_on_the_board(hub) -> None:
    client, engine = hub
    other_owners(engine)
    assert client.get("/homework").json()["soon"] == []


def test_copies_of_handed_in_work_are_not_asked_for_again(hub) -> None:
    """Combined classes import the same work into two groups: once handed in, the copy is
    neither missing nor due (as 今日 and 成绩 count it)."""
    client, engine = hub
    c = canvas(engine)
    code = {"course_code": "CIS D022A"}
    item(
        engine,
        c,
        A,
        "3:1",
        "Lab 1",
        NOW - timedelta(days=2),
        submission_state="graded",
        submitted_at=iso(NOW - timedelta(days=3)),
        group_id=1,
        score=9,
        **code,
    )
    item(engine, c, A, "3:2", "Lab 1", NOW - timedelta(days=2), missing=True, group_id=2, **code)
    item(
        engine,
        c,
        A,
        "3:3",
        "Lab 2",
        NOW + timedelta(hours=5),
        submission_state="submitted",
        submitted_at=iso(NOW - timedelta(hours=1)),
        group_id=1,
        **code,
    )
    item(engine, c, A, "3:4", "Lab 2", NOW + timedelta(hours=5), group_id=2, **code)
    item(engine, c, A, "3:5", "Lab 3", NOW + timedelta(hours=6), group_id=2, **code)
    # A same-named assignment in another group with its own due time is real work.
    item(
        engine,
        c,
        A,
        "3:6",
        "Reflection",
        NOW - timedelta(days=5),
        submission_state="graded",
        submitted_at=iso(NOW - timedelta(days=6)),
        group_id=1,
        **code,
    )
    item(engine, c, A, "3:7", "Reflection", NOW + timedelta(hours=8), group_id=2, **code)
    b = client.get("/homework").json()
    assert b["missing"] == []
    assert titles(b["soon"]) == ["Lab 3", "Reflection"]  # Lab 2's copy is already handed in
    assert b["reminder"]["title"] == "Lab 3"
    assert titles(b["submitted"]) == ["Lab 2", "Lab 1", "Reflection"]  # newest first


def test_open_without_a_canvas_link_is_422_not_500(hub) -> None:
    client, engine = hub
    c = canvas(engine)
    bare = item(engine, c, A, "4:1", "No link", NOW + timedelta(hours=2))
    with Session(engine) as s:
        row = s.get(SyncedItemRow, bare)
        assert row is not None
        row.url = ""
        s.commit()
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        r = client.post(f"/homework/{bare}/open", headers={"Idempotency-Key": "k-bare"})
        assert r.status_code == 422, r.text
        assert "Canvas 链接" in r.json()["detail"]
        heartbeat(ws)  # nothing was sent


def test_open_sends_the_assignment_page_once_per_key(hub) -> None:
    client, engine = hub
    ids = seed(engine)
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        r = client.post(f"/homework/{ids['soon']}/open", headers={"Idempotency-Key": "k-1"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["replayed"] is False
        assert body["action"]["status"] == "dispatched"
        sent = receive(ws)
        assert isinstance(sent, ActionRequestMsg)
        assert sent.request.idempotency_key == "homework:k-1"
        assert sent.request.params == {
            "url": "https://c/1:3",
            "expect_title_contains": "Journal 4",
        }

        again = client.post(f"/homework/{ids['soon']}/open", headers={"Idempotency-Key": "k-1"})
        assert again.status_code == 202
        assert again.headers["Idempotent-Replayed"] == "true"
        assert again.json()["action"]["id"] == body["action"]["id"]

        ws.send_text(answer(sent, ActionStatus.succeeded, "opened"))
        heartbeat(ws)  # the result is handled and nothing else was sent

    run = client.get(f"/actions/{body['action']['id']}").json()
    assert run["status"] == "succeeded"


def test_check_asks_canvas_to_sync_now(hub) -> None:
    client, engine = hub
    r = client.post("/homework/check")
    assert r.status_code == 409
    assert "Canvas" in r.json()["detail"]
    seed(engine)
    r = client.post("/homework/check")
    assert r.status_code == 202, r.text
    job_ids = r.json()["job_ids"]
    assert len(job_ids) == 1
    assert client.get(f"/jobs/{job_ids[0]}").status_code == 200


# --- T-0067: 排时间 ---------------------------------------------------------------------

UTC_NAME = "UTC"
# A fixed Monday 09:00 UTC, so free time (08:00-22:00 in the zone) is predictable.
MONDAY = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
OWNER = Actor(owner_id="local", source="test")


def plan_seed(engine: Engine, due: datetime) -> str:
    return item(engine, canvas(engine), A, "5:1", "Essay 2", due, course_code="ENGL C1000")


def busy(session: Session, start: datetime, hours: float, title: str = "Class") -> None:
    schedule.create(
        session,
        OWNER,
        NewEvent(
            title=title, kind="class", starts_at=start, ends_at=start + timedelta(hours=hours)
        ),
        UTC_NAME,
    )
    session.commit()


def test_the_suggestion_is_the_earliest_free_slot_before_the_due_time(hub) -> None:
    _, engine = hub
    hid = plan_seed(engine, MONDAY + timedelta(days=1))
    with Session(engine) as s:
        busy(s, MONDAY, 2)  # 09:00-11:00 class
        busy(s, MONDAY + timedelta(hours=2, minutes=30), 1)  # 11:30-12:30: 30 min gap only
        slot = homework.suggest(s, OWNER, hid, 60, UTC, UTC_NAME, now=MONDAY)
    assert slot.reason == ""
    assert slot.starts_at == MONDAY + timedelta(hours=3, minutes=30)  # 12:30
    assert slot.ends_at == MONDAY + timedelta(hours=4, minutes=30)


def test_the_suggestion_starts_on_a_quarter_hour(hub) -> None:
    _, engine = hub
    hid = plan_seed(engine, MONDAY + timedelta(days=1))
    with Session(engine) as s:
        slot = homework.suggest(s, OWNER, hid, 45, UTC, UTC_NAME, now=MONDAY + timedelta(minutes=7))
    assert slot.starts_at == MONDAY + timedelta(minutes=15)


def test_no_suggestion_when_nothing_fits_before_the_due_time(hub) -> None:
    _, engine = hub
    hid = plan_seed(engine, MONDAY + timedelta(hours=3))
    with Session(engine) as s:
        busy(s, MONDAY, 3)
        slot = homework.suggest(s, OWNER, hid, 60, UTC, UTC_NAME, now=MONDAY)
    assert slot.starts_at is None
    assert slot.reason == "截止前没有连续 60 分钟的空闲时间"


def test_planning_puts_one_block_on_the_schedule_and_the_board_shows_it(hub) -> None:
    client, engine = hub
    hid = plan_seed(engine, NOW + timedelta(days=2))
    start = (NOW + timedelta(hours=5)).replace(microsecond=0)
    body = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    r = client.post(f"/homework/{hid}/plan", json=body)
    assert r.status_code == 201, r.text
    planned = r.json()
    again = client.post(f"/homework/{hid}/plan", json=body)  # one block per homework
    assert again.status_code == 200
    assert again.json()["event_id"] == planned["event_id"]
    with Session(engine) as s:
        (event,) = schedule.events(s, OWNER)
    assert event.title == "写作业：Essay 2"
    assert event.kind == "task"
    assert f"homework:{hid}" in event.notes and "https://c/5:1" in event.notes
    row = client.get("/homework").json()["week"][0]
    assert row["planned"]["event_id"] == planned["event_id"]
    # deleting the block on 日程 clears it here too
    assert client.delete(f"/schedule/events/{planned['event_id']}").status_code == 204
    assert client.get("/homework").json()["week"][0]["planned"] is None


def test_submitted_unknown_or_bad_blocks_cannot_be_planned(hub) -> None:
    client, engine = hub
    ids = seed(engine)
    start = NOW + timedelta(hours=1)
    body = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    assert client.post(f"/homework/{ids['handed']}/plan", json=body).status_code == 409
    assert client.get(f"/homework/{ids['handed']}/slot").status_code == 409
    assert client.post("/homework/nope/plan", json=body).status_code == 404
    assert client.post(f"/homework/{other_owners(engine)}/plan", json=body).status_code == 404
    past = NOW - timedelta(hours=3)
    old = {"starts_at": past.isoformat(), "ends_at": (past + timedelta(hours=1)).isoformat()}
    assert client.post(f"/homework/{ids['week']}/plan", json=old).status_code == 422
    naive = {"starts_at": "2026-11-23T10:00:00", "ends_at": "2026-11-23T11:00:00"}
    assert client.post(f"/homework/{ids['week']}/plan", json=naive).status_code == 422
    long = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=9)).isoformat()}
    assert client.post(f"/homework/{ids['week']}/plan", json=long).status_code == 422
    with Session(engine) as s:
        assert schedule.events(s, OWNER) == []


def test_a_block_that_has_passed_lets_the_user_plan_again(hub) -> None:
    _, engine = hub
    hid = plan_seed(engine, MONDAY + timedelta(days=3))
    first = HomeworkPlan(starts_at=MONDAY + timedelta(hours=1), ends_at=MONDAY + timedelta(hours=2))
    with Session(engine) as s:
        block, created = homework.plan(s, OWNER, hid, first, UTC_NAME, now=MONDAY)
        s.commit()
        assert created
        assert homework.board(s, OWNER, now=MONDAY).week[0].planned == block
        later = MONDAY + timedelta(hours=3)  # the block is over and the work is not handed in
        assert homework.board(s, OWNER, now=later).week[0].planned is None
        again = HomeworkPlan(
            starts_at=later + timedelta(hours=1), ends_at=later + timedelta(hours=2)
        )
        new_block, created = homework.plan(s, OWNER, hid, again, UTC_NAME, now=later)
        s.commit()
    assert created and new_block.event_id != block.event_id


def test_only_a_task_block_with_the_exact_marker_counts(hub) -> None:
    client, engine = hub
    hid = plan_seed(engine, NOW + timedelta(days=2))
    start = NOW + timedelta(hours=2)
    with Session(engine) as s:
        for kind, notes in (("other", f"homework:{hid}"), ("task", f"homework: read {hid}")):
            schedule.create(
                s,
                OWNER,
                NewEvent(
                    title="mine",
                    kind=kind,
                    starts_at=start,
                    ends_at=start + timedelta(hours=1),
                    notes=notes,
                ),
                UTC_NAME,
            )
        s.commit()
    assert client.get("/homework").json()["week"][0]["planned"] is None
