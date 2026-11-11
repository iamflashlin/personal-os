"""A fake desktop agent driven through TestClient's WebSocket session."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.testclient import WebSocketTestSession

from apps.hub.audit import service as audit
from apps.hub.core.db import DB_FILENAME
from packages.contracts.actions import ActionName
from packages.contracts.agent_protocol import (
    AGENT_WS_PATH,
    HUB_TO_AGENT,
    Heartbeat,
    HeartbeatAck,
    Hello,
    HubToAgent,
    Welcome,
)

# Absolute, so the Host header is 127.0.0.1, which the Hub's TrustedHost check allows.
WS_URL = f"ws://127.0.0.1{AGENT_WS_PATH}"
ALL_ACTIONS = tuple(ActionName)


def pair(client: TestClient, name: str = "test-pc") -> tuple[str, str]:
    code = client.post("/devices/pairing-codes")
    assert code.status_code == 201, code.text
    paired = client.post(
        "/devices/pair",
        json={"code": code.json()["code"], "device_name": name, "platform": "windows"},
    )
    assert paired.status_code == 201, paired.text
    return paired.json()["device_id"], paired.json()["token"]


def connect(client: TestClient, token: str | None, **headers: str) -> WebSocketTestSession:
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return client.websocket_connect(WS_URL, headers=headers)


def receive(ws: WebSocketTestSession) -> HubToAgent:
    return HUB_TO_AGENT.validate_json(ws.receive_text())


def hello(ws: WebSocketTestSession, actions: tuple[ActionName, ...] = ALL_ACTIONS) -> Welcome:
    ws.send_text(
        Hello(
            agent_version="test", platform="windows", supported_actions=list(actions)
        ).model_dump_json()
    )
    welcome = receive(ws)
    assert isinstance(welcome, Welcome), welcome
    return welcome


def heartbeat(ws: WebSocketTestSession) -> None:
    """Round-trip a heartbeat. The Hub handles frames in order, so once the ack is back,
    every frame sent before it has been processed and nothing else was sent in between."""
    ws.send_text(Heartbeat().model_dump_json())
    ack = receive(ws)
    assert isinstance(ack, HeartbeatAck), f"expected only a heartbeat_ack, got {ack!r}"


def audit_events(client: TestClient, entity_id: str | None = None) -> list[audit.AuditEvent]:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        return audit.list_events(session, "local", entity_id)


def rows(data_dir: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as db:
        return db.execute(sql, params).fetchall()


def execute(data_dir: Path, sql: str, *params: Any) -> None:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as db:
        db.execute(sql, params)
        db.commit()
