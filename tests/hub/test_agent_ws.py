from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.hub.core.settings import Settings
from packages.contracts.agent_protocol import CloseCode, Heartbeat
from tests.hub.agent_support import audit_events, connect, heartbeat, hello, pair, rows
from tests.hub.support import hub_client


def refused(client: TestClient, token: str | None, **headers: str) -> int:
    """The close code of a handshake the Hub refuses; a real server answers it with 403."""
    with pytest.raises(WebSocketDisconnect) as refusal, connect(client, token, **headers):
        pass
    return refusal.value.code


def closed_with(ws: object) -> int:
    with pytest.raises(WebSocketDisconnect) as closing:
        ws.receive_text()  # type: ignore[attr-defined]
    return closing.value.code


@pytest.fixture
def fast_client(data_dir: Path) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, agent_heartbeat_s=0.2)) as c:
        yield c


def test_handshake_is_refused_without_a_valid_token(client: TestClient) -> None:
    device_id, token = pair(client)
    assert refused(client, None) == CloseCode.protocol_error
    assert refused(client, "posd_" + "x" * 43) == CloseCode.protocol_error
    assert refused(client, "not-a-token") == CloseCode.protocol_error
    client.post(f"/devices/{device_id}/revoke")
    assert refused(client, token) == CloseCode.protocol_error


def test_any_origin_header_is_refused_even_with_a_valid_token(client: TestClient) -> None:
    _, token = pair(client)
    assert refused(client, token, origin="http://127.0.0.1:8765") == CloseCode.protocol_error
    assert refused(client, token, origin="null") == CloseCode.protocol_error


def test_hello_welcome_heartbeat_and_status(client: TestClient, data_dir: Path) -> None:
    device_id, token = pair(client, "desk")
    assert client.get("/agent/status").json()["online"] is False
    with connect(client, token) as ws:
        welcome = hello(ws)
        assert welcome.device_id == device_id
        assert welcome.heartbeat_interval_s == 15.0
        heartbeat(ws)
        status = client.get("/agent/status").json()
        assert status["online"] is True
        assert (status["device_id"], status["device_name"]) == (device_id, "desk")
    assert client.get("/agent/status").json() == {
        "online": False,
        "device_id": None,
        "device_name": None,
        "connected_at": None,
        "last_heartbeat_at": None,
    }
    ((connected, disconnected),) = rows(
        data_dir, "SELECT last_connected_at, last_disconnected_at FROM device"
    )
    assert connected is not None and disconnected is not None
    actions = [e.action for e in audit_events(client, device_id)]
    assert actions == ["device.pair", "device.connect", "device.disconnect"]


@pytest.mark.parametrize(
    "first",
    [Heartbeat().model_dump_json(), "not json", '{"type": "hello"}', '{"v": 2, "type": "x"}'],
)
def test_the_first_frame_must_be_a_valid_hello(client: TestClient, first: str) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        ws.send_text(first)
        assert closed_with(ws) == CloseCode.protocol_error
    assert client.get("/agent/status").json()["online"] is False


def test_binary_frames_and_a_second_hello_are_protocol_errors(client: TestClient) -> None:
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        ws.send_bytes(b"\x00")
        assert closed_with(ws) == CloseCode.protocol_error
    with connect(client, token) as ws:
        hello(ws)
        ws.send_text(
            '{"type": "hello", "agent_version": "x", "platform": "windows", '
            '"supported_actions": []}'
        )
        assert closed_with(ws) == CloseCode.protocol_error


def test_silence_closes_with_heartbeat_timeout(fast_client: TestClient) -> None:
    _, token = pair(fast_client)
    with connect(fast_client, token) as ws:
        hello(ws)
        heartbeat(ws)
        assert closed_with(ws) == CloseCode.heartbeat_timeout
    assert fast_client.get("/agent/status").json()["online"] is False


def test_a_silent_socket_never_gets_past_the_handshake(fast_client: TestClient) -> None:
    _, token = pair(fast_client)
    with connect(fast_client, token) as ws:
        assert closed_with(ws) == CloseCode.heartbeat_timeout


def test_a_newer_agent_replaces_the_older_one(client: TestClient) -> None:
    _, token = pair(client)
    second_id, second_token = pair(client, "second")
    with connect(client, token) as old:
        hello(old)
        with connect(client, second_token) as new:
            hello(new)
            assert closed_with(old) == CloseCode.replaced
            heartbeat(new)
            assert client.get("/agent/status").json()["device_id"] == second_id
        assert client.get("/agent/status").json()["online"] is False


def test_revoking_closes_the_live_socket_with_4401(client: TestClient) -> None:
    device_id, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        assert client.post(f"/devices/{device_id}/revoke").status_code == 200
        assert closed_with(ws) == CloseCode.unauthorized
        assert client.get("/agent/status").json()["online"] is False
    assert refused(client, token) == CloseCode.protocol_error


def test_a_revoke_during_the_handshake_closes_right_after_welcome(
    client: TestClient,
) -> None:
    device_id, token = pair(client)
    with connect(client, token) as ws:  # authenticated, hello not sent yet
        client.post(f"/devices/{device_id}/revoke")
        hello(ws)
        assert closed_with(ws) == CloseCode.unauthorized
    assert client.get("/agent/status").json()["online"] is False


def test_revoking_another_device_leaves_the_live_one_alone(client: TestClient) -> None:
    other_id, _ = pair(client, "other")
    _, token = pair(client)
    with connect(client, token) as ws:
        hello(ws)
        client.post(f"/devices/{other_id}/revoke")
        heartbeat(ws)
        assert client.get("/agent/status").json()["online"] is True
