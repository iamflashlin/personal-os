from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.hub.actions import service as actions_service
from apps.hub.core.domain import Conflict
from apps.hub.core.settings import Settings
from apps.hub.devices import service as devices_service
from packages.contracts.actions import (
    ACTION_SPECS,
    ActionEvidenceKind,
    ActionName,
    ActionResult,
    ActionStatus,
    EvidenceItem,
    RiskLevel,
)
from packages.contracts.agent_protocol import ActionRequestMsg, ActionResultMsg, CloseCode
from tests.hub.agent_support import (
    audit_events,
    connect,
    execute,
    heartbeat,
    hello,
    pair,
    receive,
    rows,
)
from tests.hub.support import hub_client

OPEN_URL = {
    "name": "open_url",
    "params": {"url": "https://example.com/plan", "expect_title_contains": "Plan"},
}
TITLE = {"expect_title_contains": "x"}


def post(client: TestClient, body: dict[str, Any], key: str | None = "k-1") -> Any:
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post("/actions", json=body, headers=headers)


def answer(request: ActionRequestMsg, status: ActionStatus, message: str = "") -> str:
    now = datetime.now(UTC)
    result = ActionResult(
        action_id=request.request.action_id,
        idempotency_key=request.request.idempotency_key,
        status=status,
        message=message,
        evidence=[
            EvidenceItem(
                kind=ActionEvidenceKind.window,
                summary="window title contains Plan",
                data={"title": "Plan - Browser", "pid": 42},
                captured_at=now,
            )
        ],
        started_at=now,
        finished_at=now,
    )
    return ActionResultMsg(result=result).model_dump_json()


def run_count(data_dir: Path) -> int:
    return rows(data_dir, "SELECT count(*) FROM action_run")[0][0]


def test_offline_gives_503_writes_no_run_and_keeps_the_key(
    client: TestClient, data_dir: Path
) -> None:
    _, token = pair(client)
    offline = post(client, OPEN_URL)
    assert offline.status_code == 503
    assert offline.json()["detail"] == "agent offline"
    assert run_count(data_dir) == 0
    with connect(client, token) as ws:
        hello(ws)
        assert post(client, OPEN_URL).status_code == 202
        assert isinstance(receive(ws), ActionRequestMsg)


def test_a_round_trip_stores_the_result_and_its_evidence(client: TestClient) -> None:
    device_id, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        created = post(client, OPEN_URL)
        assert created.status_code == 202, created.text
        run = created.json()
        assert (run["status"], run["device_id"], run["risk_level"]) == (
            "dispatched",
            device_id,
            "P1",
        )

        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
        assert request.request.action_id == run["id"]
        assert request.request.idempotency_key == "k-1"
        assert request.request.name == ActionName.open_url
        assert request.request.params == OPEN_URL["params"]
        assert request.request.timeout_s == 20.0

        ws.send_text(answer(request, ActionStatus.succeeded, "opened"))
        heartbeat(ws)

    stored = client.get(f"/actions/{run['id']}").json()
    assert (stored["status"], stored["message"]) == ("succeeded", "opened")
    assert stored["evidence"][0]["data"] == {"title": "Plan - Browser", "pid": 42}
    assert stored["finished_at"] is not None
    assert [r["id"] for r in client.get("/actions").json()] == [run["id"]]


def test_a_replay_returns_the_same_run_and_sends_nothing(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        first = post(client, OPEN_URL)
        assert isinstance(receive(ws), ActionRequestMsg)
        again = post(client, OPEN_URL)
        assert again.status_code == 202
        assert again.headers["Idempotent-Replayed"] == "true"
        assert "Idempotent-Replayed" not in first.headers
        assert again.json() == first.json()
        heartbeat(ws)  # the next frame is the ack: no second action_request was sent


def test_a_replay_works_while_the_agent_is_offline(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        first = post(client, OPEN_URL).json()
    again = post(client, OPEN_URL)
    assert again.status_code == 202
    assert again.json()["id"] == first["id"]


def test_the_same_key_with_a_different_body_gives_422(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        post(client, OPEN_URL)
        receive(ws)
        other = {**OPEN_URL, "params": {**OPEN_URL["params"], "url": "https://example.org/"}}
        assert post(client, other).status_code == 422
        heartbeat(ws)


def test_a_disconnect_mid_flight_marks_the_run_lost(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        receive(ws)
    stored = client.get(f"/actions/{run['id']}").json()
    assert stored["status"] == "lost"
    assert post(client, OPEN_URL).json()["status"] == "lost"  # replayed, never resent


def test_a_late_result_for_a_lost_run_is_still_recorded(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
    with connect(client, token) as ws:
        hello(ws)
        ws.send_text(answer(request, ActionStatus.succeeded))
        heartbeat(ws)
    assert client.get(f"/actions/{run['id']}").json()["status"] == "succeeded"


def test_runs_left_dispatched_by_a_crash_are_lost_after_restart(data_dir: Path) -> None:
    with hub_client(Settings(data_dir=data_dir)) as client:
        _, token = pair(client)
        with connect(client, token) as ws:
            hello(ws)
            run = post(client, OPEN_URL).json()
            receive(ws)
    # What a killed Hub leaves behind: the run committed, no disconnect handler ran.
    execute(data_dir, "UPDATE action_run SET status = 'dispatched'")
    with hub_client(Settings(data_dir=data_dir)) as client:
        assert client.get(f"/actions/{run['id']}").json()["status"] == "lost"


def test_p2_and_above_are_refused_with_403(
    client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    risky = {
        name: replace(spec, risk=RiskLevel.P2) if name == ActionName.open_url else spec
        for name, spec in ACTION_SPECS.items()
    }
    monkeypatch.setattr(actions_service, "ACTION_SPECS", MappingProxyType(risky))
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        assert post(client, OPEN_URL).status_code == 403
        heartbeat(ws)
    assert run_count(data_dir) == 0
    dispatches = [e for e in audit_events(client) if e.action == "action_run.dispatch"]
    assert [e.result for e in dispatches] == ["forbidden"]


def test_an_action_the_agent_does_not_support_gives_409(client: TestClient, data_dir: Path) -> None:
    _, token = pair(client)
    folder = {"name": "open_folder_in_editor", "params": {"path": "D:\\dev\\notes"}}
    with connect(client, token) as ws:
        hello(ws, actions=(ActionName.open_url,))
        assert post(client, folder).status_code == 409
        heartbeat(ws)
    assert run_count(data_dir) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"name": "open_url", "params": {"url": "file:///C:/Windows", "expect_title_contains": "x"}},
        {
            "name": "open_url",
            "params": {"url": "javascript:alert(1)", "expect_title_contains": "x"},
        },
        {"name": "open_url", "params": {"url": "https://example.com"}},
        {"name": "open_folder_in_editor", "params": {"path": "notes"}},
        {"name": "open_folder_in_editor", "params": {"path": "D:\\a & calc"}},
        {"name": "open_folder_in_editor", "params": {"path": 'D:\\a" --install-extension x'}},
        {"name": "launch_app", "params": {}},
    ],
)
def test_invalid_or_unknown_actions_give_422(
    client: TestClient, data_dir: Path, body: dict[str, Any]
) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        assert post(client, body).status_code == 422
        heartbeat(ws)
    assert run_count(data_dir) == 0
    if body["name"] != "launch_app":  # an unknown name never reaches the service
        dispatches = [e for e in audit_events(client) if e.action == "action_run.dispatch"]
        assert [e.result for e in dispatches] == ["invalid"]


def test_the_idempotency_key_header_is_required(client: TestClient) -> None:
    assert post(client, OPEN_URL, key=None).status_code == 422


def test_a_result_for_a_run_this_device_was_not_sent_is_refused(client: TestClient) -> None:
    _, other_token = pair(client, "other")
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
    with connect(client, other_token) as ws:
        hello(ws)
        ws.send_text(answer(request, ActionStatus.succeeded))
        heartbeat(ws)  # the connection survives the bad frame
    assert client.get(f"/actions/{run['id']}").json()["status"] == "lost"
    rejected = [e for e in audit_events(client, run["id"]) if e.action == "action_run.result"]
    assert [e.result for e in rejected] == ["rejected"]


def test_secrets_in_agent_messages_are_redacted(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
        ws.send_text(answer(request, ActionStatus.failed, "header token=abc123secret"))
        heartbeat(ws)
    assert "abc123secret" not in client.get(f"/actions/{run['id']}").json()["message"]


def test_each_write_is_audited_once(client: TestClient) -> None:
    device_id, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
        post(client, OPEN_URL)
        ws.send_text(answer(request, ActionStatus.succeeded))
        heartbeat(ws)
    events = [(e.action, e.result, e.actor) for e in audit_events(client, run["id"])]
    assert events == [
        ("action_run.dispatch", "ok", "owner:local"),
        ("action_run.dispatch", "replayed", "owner:local"),
        ("action_run.result", "ok", f"device:{device_id}"),
    ]
    refused = post(client, OPEN_URL, key="k-2")
    assert refused.status_code == 503
    assert [e.result for e in audit_events(client) if e.action == "action_run.dispatch"][-1] == (
        "unavailable"
    )


def test_a_link_that_dropped_during_dispatch_gets_a_lost_run_and_no_frame(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    links: devices_service.AgentLinks = client.app.state.agent_links  # type: ignore[attr-defined]
    original = actions_service.begin

    def begin_then_drop(*args: Any, **kwargs: Any) -> actions_service.Dispatch:
        dispatch = original(*args, **kwargs)
        link = links.current("local")
        assert link is not None
        links.detach(link)
        return dispatch

    monkeypatch.setattr(actions_service, "begin", begin_then_drop)
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        created = post(client, OPEN_URL)
        assert created.json()["status"] == "lost"
        heartbeat(ws)  # no action_request was sent


def test_a_reconnect_of_the_same_device_loses_only_the_old_links_runs(
    client: TestClient,
) -> None:
    _, token = pair(client)
    with connect(client, token) as old:
        hello(old)
        first = post(client, OPEN_URL, key="old").json()
        assert isinstance(receive(old), ActionRequestMsg)
        with connect(client, token) as new:
            hello(new)
            with pytest.raises(WebSocketDisconnect) as closing:
                old.receive_text()
            assert closing.value.code == CloseCode.replaced
            second = post(client, OPEN_URL, key="new").json()
            assert isinstance(receive(new), ActionRequestMsg)
            heartbeat(new)
            old.close()  # the old handler finishes; only its own run becomes lost
            heartbeat(new)
            assert client.get(f"/actions/{first['id']}").json()["status"] == "lost"
            assert client.get(f"/actions/{second['id']}").json()["status"] == "dispatched"


def test_a_run_in_flight_when_the_device_is_revoked_becomes_lost(client: TestClient) -> None:
    device_id, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        receive(ws)
        client.post(f"/devices/{device_id}/revoke")
    assert client.get(f"/actions/{run['id']}").json()["status"] == "lost"


def test_failing_to_store_a_result_keeps_the_run_in_flight(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(_text: str) -> str:
        raise Conflict("database busy")

    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        run = post(client, OPEN_URL).json()
        request = receive(ws)
        assert isinstance(request, ActionRequestMsg)
        # Fails inside record_result's transaction, the way a busy database would.
        monkeypatch.setattr(actions_service.audit, "redact_text", busy)
        ws.send_text(answer(request, ActionStatus.succeeded))
        heartbeat(ws)  # the link survives the failed write
        monkeypatch.undo()
    assert client.get(f"/actions/{run['id']}").json()["status"] == "lost"
