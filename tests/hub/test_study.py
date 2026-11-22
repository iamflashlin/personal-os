# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation)
"""开始学习 (ADR 0042): plan from the course map, start on the PC, finish, next."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.hub.actions import service as actions_service
from apps.hub.core.domain import Unavailable
from apps.hub.core.settings import Settings
from packages.contracts.actions import ActionStatus
from packages.contracts.agent_protocol import ActionRequestMsg
from tests.hub.agent_support import connect, heartbeat, hello, pair, receive
from tests.hub.support import hub_client
from tests.hub.test_actions import answer
from tests.hub.test_course_map import course_map, seed
from tests.hub.test_gpa import canvas, item

NOW = datetime.now(UTC)


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        engine = client.app.state.engine  # type: ignore[attr-defined]
        seed(engine)
        assert client.put("/academic/maps/MATH D001A", json=course_map()).status_code == 200
        yield client, engine


def start(client: TestClient, key: str = "s-1", code: str = "MATH D001A") -> Any:
    return client.post(
        "/study/sessions", json={"course_code": code}, headers={"Idempotency-Key": key}
    )


def test_the_plan_follows_the_nearest_exam_weakest_section_first(hub) -> None:
    client, _ = hub
    r = client.get("/study/plans/math d001a")
    assert r.status_code == 200, r.text
    plan = r.json()
    nxt = plan["next"]
    # Quiz #4 gave 3.4 50%: it needs review, so it comes before the rest of Exam 2's scope.
    assert nxt["key"] == "3.4"
    assert nxt["title"] == "复习 3.4 Chain rule"
    assert nxt["exam"] == "Exam 2"
    assert "练习成绩偏低" in nxt["why"] and "Exam 2 还有" in nxt["why"]
    assert nxt["page"] == 31
    steps = plan["steps"]
    assert [s["action"] for s in steps] == ["open_url", "open_url"]
    assert steps[0]["label"] == "打开 3.4 的老师资料"
    assert steps[0]["params"]["expect_title_contains"] == "Math1A-Sec3.4"
    # the notes' window title holds the file name without ".pdf"
    assert steps[1]["label"] == "打开讲义（第 31 页）"
    assert steps[1]["params"] == {"url": "https://c/m1", "expect_title_contains": "Notes"}
    assert plan["last"] is None


def test_a_course_without_an_upcoming_exam_still_gets_a_plan(hub) -> None:
    client, _ = hub
    past = (NOW - timedelta(days=2)).isoformat()
    body = course_map(exams=[{"name": "Exam 2", "at": past, "scope": ["3.4"], "match": "x*"}])
    assert client.put("/academic/maps/MATH D001A", json=body).status_code == 200
    plan = client.get("/study/plans/MATH D001A").json()
    assert plan["next"]["exam"] == ""
    assert plan["next"]["key"] == "3.4"  # still the weakest section
    assert plan["next"]["why"] == "练习成绩偏低（最近没有考试）"


def test_unknown_course_is_404(hub) -> None:
    client, _ = hub
    assert client.get("/study/plans/NOPE 1").status_code == 404
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        assert start(client, code="NOPE 1").status_code == 404
        heartbeat(ws)  # nothing was sent


def test_start_without_an_agent_is_503_and_stores_nothing(hub) -> None:
    client, _ = hub
    r = start(client)
    assert r.status_code == 503
    assert "电脑助手没有连上" in r.json()["detail"]
    assert client.get("/study/plans/MATH D001A").json()["last"] is None


def test_start_sends_each_step_once_and_reports_what_the_agent_did(hub) -> None:
    client, _ = hub
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        r = start(client)
        assert r.status_code == 201, r.text
        session = r.json()
        assert [s["status"] for s in session["steps"]] == ["dispatched", "dispatched"]
        first, second = receive(ws), receive(ws)
        assert isinstance(first, ActionRequestMsg) and isinstance(second, ActionRequestMsg)
        assert first.request.idempotency_key == "study:s-1:0"
        assert first.request.params["expect_title_contains"] == "Math1A-Sec3.4"

        again = start(client)  # the same key: the same session, nothing sent
        assert again.status_code == 201
        assert again.headers["Idempotent-Replayed"] == "true"
        assert "Idempotent-Replayed" not in r.headers
        assert again.json()["id"] == session["id"]

        ws.send_text(answer(first, ActionStatus.succeeded, "opened"))
        ws.send_text(answer(second, ActionStatus.failed, "no window titled 'Notes'"))
        heartbeat(ws)  # both results handled, and no third request was sent

    got = client.get(f"/study/sessions/{session['id']}").json()
    assert [s["status"] for s in got["steps"]] == ["succeeded", "failed"]
    assert got["steps"][1]["message"] == "no window titled 'Notes'"
    assert got["next"]["key"] == "3.4"
    assert client.get("/study/plans/MATH D001A").json()["last"]["title"] == "复习 3.4 Chain rule"


def test_finish_checks_the_version_and_the_next_plan_moves_on(hub) -> None:
    client, _ = hub
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        session = start(client).json()
        receive(ws)
        receive(ws)
    url = f"/study/sessions/{session['id']}/finish"
    stale = client.post(url, json={"version": session["version"] + 1})
    assert stale.status_code == 409
    done = client.post(url, json={"version": session["version"], "note": "链式法则做了 5 题"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "finished"
    assert done.json()["finished_at"] is not None
    assert client.post(url, json={"version": done.json()["version"]}).status_code == 409

    plan = client.get("/study/plans/MATH D001A").json()
    assert plan["next"]["key"] not in ("3.4", "")  # 3.4 was just studied
    assert plan["last"]["finished_at"] is not None


def test_next_picks_the_course_with_the_nearest_exam(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    item(engine, iid, "canvas_course", "e", "ECON", course_code="F26 ECON C2002 01 Macro")
    econ = {
        "course_code": "ECON C2002",
        "material": "Econ notes.pdf",
        "concepts": [
            {"key": "ch1", "kind": "chapter", "title": "GDP"},
            {"key": "1.1", "kind": "section", "parent": "ch1", "title": "Output", "page": 1},
        ],
        "exams": [
            {
                "name": "Midterm",
                "at": (NOW + timedelta(days=1)).isoformat(),
                "scope": ["1.1"],
                "match": "Midterm*",
            }
        ],
    }
    assert client.put("/academic/maps/ECON C2002", json=econ).status_code == 200
    assert client.get("/study/next").json()["course_code"] == "ECON C2002"


def test_next_without_any_map_is_404(tmp_path: Path) -> None:
    with hub_client(Settings(data_dir=tmp_path / "d", jobs_enabled=False)) as client:
        assert client.get("/study/next").status_code == 404


def test_a_section_without_its_own_links_still_opens_the_course_notes(hub) -> None:
    client, _ = hub
    body = course_map(
        concepts=[
            {"key": "ch9", "kind": "chapter", "title": "New"},
            {"key": "9.1", "kind": "section", "parent": "ch9", "title": "Fresh", "page": 90},
        ],
        exams=[],
    )
    assert client.put("/academic/maps/MATH D001A", json=body).status_code == 200
    plan = client.get("/study/plans/MATH D001A").json()
    assert plan["next"]["key"] == "9.1"
    assert [s["params"]["url"] for s in plan["steps"]] == ["https://c/m1"]


def test_a_replay_while_the_agent_is_offline_returns_the_stored_session(hub) -> None:
    client, _ = hub
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        first = start(client).json()
        receive(ws)
        receive(ws)
    again = start(client)
    assert again.status_code == 201
    assert again.json()["id"] == first["id"]
    assert again.headers["Idempotent-Replayed"] == "true"


def test_the_same_key_for_another_course_is_refused(hub) -> None:
    client, _ = hub
    other = course_map(course_code="ECON C2002")
    assert client.put("/academic/maps/ECON C2002", json=other).status_code == 200
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        start(client)
        receive(ws)
        receive(ws)
        r = start(client, code="ECON C2002")
        assert r.status_code == 422
        heartbeat(ws)


def test_a_start_cut_short_shows_what_was_sent_and_a_replay_sends_the_rest(
    hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = hub
    real = actions_service.dispatch
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise Unavailable("agent offline")
        return await real(*args, **kwargs)

    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        monkeypatch.setattr(actions_service, "dispatch", flaky)
        session = start(client).json()
        monkeypatch.setattr(actions_service, "dispatch", real)
        assert [s["status"] for s in session["steps"]] == ["dispatched", "not_sent"]
        assert isinstance(receive(ws), ActionRequestMsg)

        replay = start(client).json()
        assert replay["id"] == session["id"]
        assert [s["status"] for s in replay["steps"]] == ["dispatched", "dispatched"]
        resent = receive(ws)
        assert isinstance(resent, ActionRequestMsg)
        assert resent.request.idempotency_key == "study:s-1:1"  # only the unsent step
        heartbeat(ws)
