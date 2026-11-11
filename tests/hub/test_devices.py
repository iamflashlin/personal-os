import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from apps.hub.core.db import DB_FILENAME
from packages.contracts.devices import PAIRING_CODE_PATTERN, TOKEN_PREFIX
from tests.hub.agent_support import audit_events, execute, pair, rows

MISSING = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def new_code(client: TestClient) -> str:
    response = client.post("/devices/pairing-codes")
    assert response.status_code == 201, response.text
    return response.json()["code"]


def pair_with(client: TestClient, code: str) -> int:
    body = {"code": code, "device_name": "pc", "platform": "windows"}
    return client.post("/devices/pair", json=body).status_code


def test_pairing_code_is_shown_once_and_expires_in_five_minutes(client: TestClient) -> None:
    before = datetime.now(UTC)
    response = client.post("/devices/pairing-codes").json()
    assert re.fullmatch(PAIRING_CODE_PATTERN, response["code"])
    expires_at = datetime.fromisoformat(response["expires_at"])
    assert before + timedelta(minutes=4) < expires_at <= datetime.now(UTC) + timedelta(minutes=5)


def test_a_code_pairs_exactly_once(client: TestClient) -> None:
    code = new_code(client)
    assert pair_with(client, code) == 201
    assert pair_with(client, code) == 403


def test_codes_are_case_and_dash_insensitive(client: TestClient) -> None:
    code = new_code(client)
    assert pair_with(client, code.replace("-", "").lower()) == 201


def test_an_expired_code_is_refused(client: TestClient, data_dir: Path) -> None:
    code = new_code(client)
    execute(data_dir, "UPDATE pairing_code SET expires_at = '2000-01-01 00:00:00'")
    assert pair_with(client, code) == 403


def test_an_unknown_or_malformed_code_is_refused(client: TestClient) -> None:
    new_code(client)
    assert pair_with(client, "0000-0000") == 403
    assert pair_with(client, "IIII-LLLL") == 422  # I and L are not Crockford digits


def test_only_hashes_are_stored_and_neither_secret_reaches_the_audit_log(
    client: TestClient, data_dir: Path
) -> None:
    code = new_code(client)
    paired = client.post(
        "/devices/pair", json={"code": code, "device_name": "pc", "platform": "windows"}
    ).json()
    token = paired["token"]
    assert token.startswith(TOKEN_PREFIX)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    code_hash = hashlib.sha256(code.replace("-", "").encode()).hexdigest()

    assert rows(data_dir, "SELECT token_hash FROM device") == [(token_hash,)]
    assert rows(data_dir, "SELECT code_hash FROM pairing_code") == [(code_hash,)]
    stored = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    assert token.encode() not in stored
    assert code.replace("-", "").encode() not in stored

    logged = json.dumps([e.model_dump(mode="json") for e in audit_events(client)])
    for secret in (token, token_hash, code, code.replace("-", ""), code_hash):
        assert secret not in logged


def test_devices_are_listed_and_revoked_once(client: TestClient) -> None:
    device_id, _ = pair(client, "laptop")
    (listed,) = client.get("/devices").json()
    assert (listed["id"], listed["name"], listed["revoked_at"]) == (device_id, "laptop", None)
    assert "token" not in json.dumps(listed)

    first = client.post(f"/devices/{device_id}/revoke")
    assert first.status_code == 200
    assert first.json()["revoked_at"] is not None
    again = client.post(f"/devices/{device_id}/revoke")
    assert again.json()["revoked_at"] == first.json()["revoked_at"]
    assert client.post(f"/devices/{MISSING}/revoke").status_code == 404


def test_every_write_is_audited_once(client: TestClient) -> None:
    code = new_code(client)
    assert pair_with(client, "0000-0000") == 403
    assert pair_with(client, code) == 201
    (device,) = client.get("/devices").json()
    client.post(f"/devices/{device['id']}/revoke")
    client.post(f"/devices/{device['id']}/revoke")

    events = [(e.action, e.result) for e in audit_events(client)]
    assert events == [
        ("pairing_code.create", "ok"),
        ("device.pair", "forbidden"),
        ("device.pair", "ok"),
        ("device.revoke", "ok"),
        ("device.revoke", "unchanged"),
    ]
    pairing = [e for e in audit_events(client) if e.action == "device.pair"]
    assert all(e.actor == "owner:local" for e in pairing)
    assert pairing[-1].entity_id == device["id"]
