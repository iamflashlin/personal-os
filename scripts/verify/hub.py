# ruff: noqa: RUF001  (Chinese sample memories use full-width punctuation on purpose)
"""Real-behaviour checks against a running Hub process.

    uv run python scripts/verify/hub.py health
    uv run python scripts/verify/hub.py crud [--audit-out audit-sample.json]
    uv run python scripts/verify/hub.py roundtrip [--manifest-out manifest-sample.json]
    uv run python scripts/verify/hub.py memory
    uv run python scripts/verify/hub.py agent
    uv run python scripts/verify/hub.py jobs
    uv run python scripts/verify/hub.py credentials
    uv run python scripts/verify/hub.py integrations
    uv run python scripts/verify/hub.py canvas
    uv run python scripts/verify/hub.py email

Each subcommand starts `python -m apps.hub` on a free 127.0.0.1 port with a fresh data
dir under `data/verify/` (gitignored, on the repo drive), talks to it over real HTTP,
then stops it. Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.hub.backup.service import table_rows  # noqa: E402
from apps.hub.core.db import DB_FILENAME, head_revision  # noqa: E402
from packages.contracts.actions import (  # noqa: E402
    ActionEvidenceKind,
    ActionName,
    ActionResult,
    ActionStatus,
    EvidenceItem,
)
from packages.contracts.agent_protocol import (  # noqa: E402
    AGENT_WS_PATH,
    HUB_TO_AGENT,
    ActionRequestMsg,
    ActionResultMsg,
    CloseCode,
    Heartbeat,
    HeartbeatAck,
    Hello,
    HubToAgent,
    Welcome,
)

STARTUP_TIMEOUT_S = 30.0


class CheckFailed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise CheckFailed(message)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running_hub(data_dir: Path) -> Iterator[httpx.Client]:
    port = free_port()
    env = {**os.environ, "POS_DATA_DIR": str(data_dir), "POS_HUB_PORT": str(port)}
    env.pop("POS_HUB_HOST", None)
    log_path = data_dir.parent / f"hub-{data_dir.name}.log"
    print(f"start  python -m apps.hub  port={port}  data_dir={data_dir}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "apps.hub"], cwd=ROOT, env=env, stdout=log, stderr=log
        )
    base_url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            deadline = time.monotonic() + STARTUP_TIMEOUT_S
            while True:
                if proc.poll() is not None:
                    check(False, f"hub process stayed up (exited {proc.returncode})")
                try:
                    client.get("/health")
                    break
                except httpx.TransportError:
                    if time.monotonic() > deadline:
                        check(False, f"hub answered within {STARTUP_TIMEOUT_S}s")
                    time.sleep(0.2)
            print(f"ready  {base_url}", flush=True)
            check(
                f"Uvicorn running on {base_url}" in log_path.read_text(encoding="utf-8"),
                "hub bound to loopback 127.0.0.1 by default",
            )
            yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"stop   hub exit={proc.returncode}", flush=True)
        print("--- hub log ---")
        print(log_path.read_text(encoding="utf-8").rstrip())
        print("--- end hub log ---")


def verify_health(client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    response = client.get("/health")
    print(f"GET /health -> {response.status_code} {response.text}", flush=True)
    check(response.status_code == 200, "GET /health returns 200")
    body = response.json()
    check(body.get("status") == "ok", 'status is "ok"')
    check(body.get("schema_version") == head_revision(), f"schema_version == {head_revision()}")

    db = data_dir / DB_FILENAME
    check(db.is_file(), f"database file created at {db}")
    with closing(sqlite3.connect(db)) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    check(mode == "wal", f"journal_mode is wal (got {mode})")


def _create(client: httpx.Client, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/{kind}s", json=body, headers={"Idempotency-Key": f"verify-{kind}"})
    print(f"POST /{kind}s -> {response.status_code} {response.text}", flush=True)
    check(response.status_code == 201, f"create {kind} returns 201")
    created = response.json()
    read_back = client.get(f"/{kind}s/{created['id']}")
    check(read_back.json() == created, f"GET /{kind}s/{created['id']} reads back the same {kind}")
    return created


def verify_crud(client: httpx.Client, data_dir: Path, args: argparse.Namespace) -> None:
    goal = _create(client, "goal", {"title": "Pass CIS course"})
    project = _create(client, "project", {"title": "CIS lab 3", "goal_id": goal["id"]})
    task = _create(
        client,
        "task",
        {
            "title": "Read lab 3 handout",
            "project_id": project["id"],
            "tags": ["course:CIS"],
            "notes": "portal login token=abc123 (should be redacted in audit)",
        },
    )
    check(task["execution_mode"] == "human_led", "course:CIS task defaults to human_led")
    workspace = _create(
        client,
        "workspace",
        {"title": "Lab 3 desk", "task_id": task["id"], "urls": ["https://example.com/lab3"]},
    )

    replay = client.post(
        "/goals", json={"title": "Pass CIS course"}, headers={"Idempotency-Key": "verify-goal"}
    )
    check(replay.json()["id"] == goal["id"], "repeated POST with same Idempotency-Key replays")
    check(len(client.get("/goals").json()) == 1, "no duplicate goal created")
    reused = client.post(
        "/goals", json={"title": "Different goal"}, headers={"Idempotency-Key": "verify-goal"}
    )
    check(reused.status_code == 422, "same Idempotency-Key with a different body returns 422")

    patched = client.patch(f"/tasks/{task['id']}", json={"version": 1, "status": "in_progress"})
    check(patched.status_code == 200 and patched.json()["version"] == 2, "PATCH bumps version")
    stale = client.patch(f"/tasks/{task['id']}", json={"version": 1, "title": "stale"})
    check(stale.status_code == 409, "stale version PATCH returns 409")
    check(client.delete(f"/workspaces/{workspace['id']}").status_code == 204, "DELETE workspace")

    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT created_at, actor, action, entity_type, entity_id, result, detail"
                " FROM audit_event ORDER BY created_at, id"
            )
        ]
    for row in rows:
        row["detail"] = json.loads(row["detail"])
    sample = json.dumps(rows, indent=2, ensure_ascii=False)
    results = [(r["action"], r["result"]) for r in rows]
    check(
        results.count(("goal.create", "replayed")) == 1
        and results.count(("goal.create", "invalid")) == 1
        and len(rows) == 9,
        f"7 writes + 1 replay + 1 rejected reuse produced 9 audit events (got {results})",
    )
    check("abc123" not in sample and "token=[REDACTED]" in sample, "audit detail is redacted")
    if args.audit_out:
        Path(args.audit_out).write_text(sample + "\n", encoding="utf-8")
        print(f"wrote {args.audit_out}", flush=True)


def _pos(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "tools.pos", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    print(f"pos {' '.join(args)} -> exit {result.returncode}", flush=True)
    print(f"  {(result.stdout + result.stderr).strip()}", flush=True)
    return result


def _dump(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: table_rows(conn, t) for t in sorted(tables)}


def _snapshot(client: httpx.Client) -> dict[str, Any]:
    return {k: client.get(f"/{k}").json() for k in ("goals", "projects", "tasks", "workspaces")}


def verify_roundtrip(client: httpx.Client, data_dir: Path, args: argparse.Namespace) -> None:
    goal = _create(client, "goal", {"title": "Move to a new machine"})
    project = _create(client, "project", {"title": "Export test", "goal_id": goal["id"]})
    task = _create(client, "task", {"title": "Export then import", "project_id": project["id"]})
    _create(client, "workspace", {"title": "Desk", "task_id": task["id"], "urls": ["x"]})
    renamed = client.patch(f"/goals/{goal['id']}", json={"version": 1, "title": "Move to a new PC"})
    check(renamed.status_code == 200, "PATCH goal before export")
    before = _snapshot(client)

    package = data_dir.parent / "export.zip"
    exported = _pos("export", "--data-dir", str(data_dir), "--out", str(package))
    check(exported.returncode == 0 and package.is_file(), "pos export while the Hub runs")
    with zipfile.ZipFile(package) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    check(manifest["schema_version"] == head_revision(), "manifest records the schema head")
    check(manifest["row_counts"]["audit_event"] == 5, "manifest counts 5 audit events")
    if args.manifest_out:
        Path(args.manifest_out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.manifest_out}", flush=True)

    restored = data_dir.parent / "restored"
    imported = _pos("import", "--in", str(package), "--data-dir", str(restored))
    check(imported.returncode == 0, "pos import into an empty directory")
    again = _pos("import", "--in", str(package), "--data-dir", str(restored))
    check(
        again.returncode == 1 and "is not empty" in again.stderr,
        "pos import refuses a non-empty directory",
    )

    with running_hub(restored) as second:
        check(second.get("/health").json()["status"] == "ok", "restored Hub /health ok")
        check(_snapshot(second) == before, "restored Hub returns identical API collections")

    original, copy = _dump(data_dir), _dump(restored)
    check(
        original == copy,
        f"every row of every table identical after restore ({', '.join(sorted(copy))})",
    )


def _remember(client: httpx.Client, body: str, **fields: Any) -> dict[str, Any]:
    response = client.post("/memories", json={"kind": "fact", "body": body, **fields})
    check(response.status_code == 201, f"remember {body!r}")
    return response.json()


def _found(client: httpx.Client, q: str, **params: Any) -> list[str]:
    response = client.get("/memories/search", params={"q": q, **params})
    print(
        f"search {q!r} -> {response.status_code} {[h['memory']['body'] for h in response.json()]}"
    )
    return [h["memory"]["body"] for h in response.json()]


def verify_memory(client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    study = _remember(client, "我喜欢早上学习 C++，晚上复习英语", kind="preference")
    _remember(client, "CIS lab 3 is due on Friday")
    guess = _remember(client, "Prefers dark mode", provenance="ai_inferred", confidence=0.4)
    private = _remember(client, "银行卡后四位 4821", sensitivity="private")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _remember(client, "old exam room B101", expires_at=past)

    check(_found(client, "早上学习") == [study["body"]], "3+ character Chinese term via FTS5")
    check(_found(client, "英语") == [study["body"]], "2-character Chinese term via substring")
    check(_found(client, "lab Friday") == ["CIS lab 3 is due on Friday"], "English, two terms")
    check(_found(client, "exam") == [], "expired memory hidden from search")

    fixed = client.patch(
        f"/memories/{study['id']}", json={"version": 1, "body": "我喜欢晚上学习 C++"}
    )
    check(fixed.status_code == 200, "correct a memory")
    check(_found(client, "早上学习") == [], "search forgets the old wording")
    check(_found(client, "晚上学习") == ["我喜欢晚上学习 C++"], "search finds the correction")

    confirmed = client.post(f"/memories/{guess['id']}/confirm", json={"version": 1})
    check(
        confirmed.json()["provenance"] == "user_confirmed" and confirmed.json()["confidence"] == 1,
        "confirm turns an AI guess into user_confirmed",
    )
    verified = client.post(
        "/memories", json={"kind": "fact", "body": "x", "provenance": "verified"}
    )
    check(verified.status_code == 422, "provenance 'verified' cannot be set through the API")

    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        details = [
            r[0]
            for r in conn.execute(
                "SELECT detail FROM audit_event WHERE entity_id = ?", (private["id"],)
            )
        ]
    check(
        bool(details) and all("4821" not in d for d in details),
        "private body never in the audit log",
    )

    package = data_dir.parent / "memory-export.zip"
    check(
        _pos("export", "--data-dir", str(data_dir), "--out", str(package)).returncode == 0, "export"
    )
    restored = data_dir.parent / "memory-restored"
    check(
        _pos("import", "--in", str(package), "--data-dir", str(restored)).returncode == 0, "import"
    )
    with running_hub(restored) as second:
        check(
            _found(second, "晚上学习") == ["我喜欢晚上学习 C++"], "restored Hub searches memories"
        )


def _ws_url(client: httpx.Client) -> str:
    return str(client.base_url).replace("http://", "ws://").rstrip("/") + AGENT_WS_PATH


def _handshake_status(client: httpx.Client, **headers: str) -> int | None:
    """The HTTP status of a refused handshake, or None if the Hub accepted it."""
    try:
        with ws_connect(_ws_url(client), additional_headers=headers, open_timeout=5):
            return None
    except InvalidStatus as exc:
        return exc.response.status_code


def _recv(ws: ClientConnection) -> HubToAgent:
    return HUB_TO_AGENT.validate_json(ws.recv(timeout=5))


def _hello(ws: ClientConnection) -> Welcome:
    ws.send(
        Hello(
            agent_version="verify", platform="windows", supported_actions=list(ActionName)
        ).model_dump_json()
    )
    welcome = _recv(ws)
    check(isinstance(welcome, Welcome), f"hello -> welcome ({type(welcome).__name__})")
    assert isinstance(welcome, Welcome)
    return welcome


def _only_ack(ws: ClientConnection, why: str) -> None:
    ws.send(Heartbeat().model_dump_json())
    frame = _recv(ws)
    check(isinstance(frame, HeartbeatAck), f"next frame is heartbeat_ack: {why}")


def _run(client: httpx.Client, run_id: str, until: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while True:
        run = client.get(f"/actions/{run_id}").json()
        if run["status"] == until or time.monotonic() > deadline:
            return run
        time.sleep(0.05)


def _pair(client: httpx.Client, code: str) -> httpx.Response:
    body = {"code": code, "device_name": "verify-pc", "platform": "windows"}
    return client.post("/devices/pair", json=body)


def _act(client: httpx.Client, key: str | None) -> httpx.Response:
    body = {
        "name": "open_url",
        "params": {"url": "https://example.com/verify", "expect_title_contains": "Example"},
    }
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post("/actions", json=body, headers=headers)


def _result(run_id: str, key: str) -> str:
    now = datetime.now(UTC)
    result = ActionResult(
        action_id=run_id,
        idempotency_key=key,
        status=ActionStatus.succeeded,
        message="opened",
        evidence=[
            EvidenceItem(
                kind=ActionEvidenceKind.window,
                summary="browser window title contains Example",
                data={"title": "Example Domain"},
                captured_at=now,
            )
        ],
        started_at=now,
        finished_at=now,
    )
    return ActionResultMsg(result=result).model_dump_json()


def verify_agent(client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    code = client.post("/devices/pairing-codes").json()["code"]
    paired = _pair(client, code)
    check(paired.status_code == 201, "POST /devices/pair with a fresh code -> 201")
    device_id, token = paired.json()["device_id"], paired.json()["token"]
    check(_pair(client, code).status_code == 403, "the same code a second time -> 403")
    bearer = {"Authorization": f"Bearer {token}"}

    check(_handshake_status(client) == 403, "handshake without a token -> HTTP 403")
    status = _handshake_status(client, **bearer, Origin="http://evil.example")
    check(status == 403, "handshake with a valid token plus an Origin header -> HTTP 403")
    check(_act(client, "verify-1").status_code == 503, "POST /actions while offline -> 503")

    with ws_connect(_ws_url(client), additional_headers=bearer, open_timeout=5) as ws:
        check(_hello(ws).device_id == device_id, "welcome names the paired device")
        _only_ack(ws, "heartbeat answered")
        agent = client.get("/agent/status").json()
        check(agent["online"] and agent["device_id"] == device_id, "GET /agent/status online")

        sent = _act(client, "verify-1")
        check(sent.status_code == 202, "the offline key was not consumed: same key now -> 202")
        run = sent.json()
        request = _recv(ws)
        check(isinstance(request, ActionRequestMsg), "one action_request frame delivered")
        assert isinstance(request, ActionRequestMsg)
        check(request.request.action_id == run["id"], "the frame carries the stored run id")

        check(_act(client, None).status_code == 422, "POST /actions without the key -> 422")
        replay = _act(client, "verify-1")
        check(
            replay.headers.get("Idempotent-Replayed") == "true"
            and replay.json()["id"] == run["id"],
            "replay returns the same run with Idempotent-Replayed: true",
        )
        _only_ack(ws, "the replay delivered no second action_request")

        ws.send(_result(run["id"], "verify-1"))
        stored = _run(client, run["id"], "succeeded")
        check(stored["status"] == "succeeded", "the agent's result is stored")
        check(stored["evidence"][0]["data"] == {"title": "Example Domain"}, "with its evidence")

        flight = _act(client, "verify-2")
        check(isinstance(_recv(ws), ActionRequestMsg), "a second action is delivered")
    lost = _run(client, flight.json()["id"], "lost")
    check(lost["status"] == "lost", "agent disconnected mid-flight -> run is lost, not resent")
    check(not client.get("/agent/status").json()["online"], "GET /agent/status offline")

    with ws_connect(_ws_url(client), additional_headers=bearer, open_timeout=5) as ws:
        _hello(ws)
        revoked = client.post(f"/devices/{device_id}/revoke")
        check(revoked.status_code == 200, "POST /devices/{id}/revoke -> 200")
        try:
            ws.recv(timeout=5)
            close_code = None
        except ConnectionClosed as exc:
            close_code = exc.rcvd.code if exc.rcvd else None
        check(close_code == CloseCode.unauthorized, f"revoke closed the socket with {close_code}")
    check(_handshake_status(client, **bearer) == 403, "reconnect with the revoked token -> 403")

    stored_bytes = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    check(token.encode() not in stored_bytes, "the token is not in the bytes of hub.sqlite*")
    check(code.replace("-", "").encode() not in stored_bytes, "nor is the pairing code")


def _scheduled_jobs(data_dir: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM job WHERE idempotency_key LIKE 'schedule:%'")
        return [dict(r) for r in rows]


def verify_jobs(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    from sqlalchemy.orm import Session

    from apps.hub.core.db import make_engine
    from apps.hub.core.domain import Actor
    from apps.hub.jobs import service as jobs

    # Its own data dir: the restart below needs the Hub stopped, which the outer one is not.
    jobs_dir = data_dir.parent / "jobs-data"
    actor = Actor(owner_id="local", source="verify")
    with running_hub(jobs_dir) as hub:
        engine = make_engine(jobs_dir)
        with Session(engine) as s:
            job = jobs.enqueue(s, actor, "system.noop", {"why": "verify"}, now=datetime.now(UTC))
            scheduled_at = datetime.now(UTC)
            jobs.ensure_schedule(s, actor, "system.noop", 1, {}, now=scheduled_at)
        deadline = time.monotonic() + 10
        while hub.get(f"/jobs/{job.id}").json()["status"] != "succeeded":
            if time.monotonic() > deadline:
                check(False, "the queued job ran within 10 s")
            time.sleep(0.2)
        check(True, "a queued job ran in the real Hub within 10 s")
        time.sleep(3.5)
        first = _scheduled_jobs(jobs_dir)
        check(len(first) >= 2, f"a 1-second schedule produced {len(first)} jobs")
        engine.dispose()
    with running_hub(jobs_dir) as hub:
        time.sleep(3.5)
        listed = hub.get("/jobs", params={"limit": 200}).json()
        check(all(j["status"] != "running" for j in listed), "nothing is left running")
    scheduled = _scheduled_jobs(jobs_dir)
    keys = [j["idempotency_key"] for j in scheduled]
    check(
        len(scheduled) > len(first),
        f"the schedule continued after the restart ({len(scheduled)} jobs)",
    )
    slots = sorted(datetime.fromisoformat(k.split(":", 2)[2]) for k in keys)
    gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(slots)]
    check(min(gaps) >= 1, f"no two jobs share a 1-second slot (smallest gap {min(gaps):.2f} s)")
    elapsed = (datetime.now(UTC) - scheduled_at).total_seconds()
    check(
        len(slots) <= elapsed + 1,
        f"{len(slots)} jobs in {elapsed:.1f} s: no burst of catch-up jobs after the restart",
    )
    states = {j["status"] for j in scheduled}
    check(states <= {"succeeded", "queued"}, f"schedule jobs ended {sorted(states)}")


def verify_credentials(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    import uuid

    import keyring

    # Its own Hub, so its secrets go under a throwaway Credential Manager service name.
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    secret = f"verify-secret-{uuid.uuid4().hex}"
    hub_dir = data_dir.parent / "credentials-data"
    os.environ["POS_CREDENTIALS_SERVICE"] = service
    owner = os.environ.get("POS_OWNER_ID", "local")
    key = f"{owner}:verify.token"
    try:
        with running_hub(hub_dir) as hub:
            put = hub.put("/credentials/verify.token", json={"secret": secret, "note": "v"})
            check(put.status_code == 200, f"PUT /credentials/verify.token -> {put.status_code}")
            check(secret not in put.text, "the response does not echo the secret")
            listed = hub.get("/credentials")
            check(secret not in listed.text, "GET /credentials lists the name, not the secret")
            check(
                keyring.get_password(service, key) == secret,
                "the secret is in Windows Credential Manager",
            )
            stored = b"".join(p.read_bytes() for p in hub_dir.glob(f"{DB_FILENAME}*"))
            check(secret.encode() not in stored, "the secret is in no byte of hub.sqlite*")
            check(hub.get("/credentials/verify.token").status_code in (404, 405), "no read route")
            gone = hub.delete("/credentials/verify.token")
            check(gone.status_code == 204, "DELETE /credentials/verify.token -> 204")
            check(keyring.get_password(service, key) is None, "the secret left Credential Manager")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(secret not in hub_log, "the secret is not in the Hub log")
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
        with contextlib.suppress(Exception):
            keyring.delete_password(service, key)


def verify_integrations(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    import threading
    import uuid
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import keyring

    token = f"feedtoken-{uuid.uuid4().hex[:16]}"
    state = {"status": 200, "body": ""}

    def calendar(*events: tuple[str, str]) -> str:
        crlf = "\r\n"
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        for uid, title in events:
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{title}"]
            lines += ["DTSTART:20261112T075900Z", "END:VEVENT"]
        return crlf.join([*lines, "END:VCALENDAR", ""])

    class Feed(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = state["body"].encode()
            self.send_response(int(state["status"]))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Feed)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    feed_url = f"http://127.0.0.1:{server.server_address[1]}/feeds/{token}.ics"
    state["body"] = calendar(("a", "Lab 3"), ("b", "Quiz 2"))

    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "integrations-data"
    os.environ["POS_CREDENTIALS_SERVICE"] = service

    def wait(hub: httpx.Client, what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 20
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    try:
        with running_hub(hub_dir) as hub:
            put = hub.put("/credentials/canvas.feed", json={"secret": feed_url})
            check(put.status_code == 200, "the private feed URL is stored as a credential")
            created = hub.post(
                "/integrations",
                json={"kind": "ics", "name": "Canvas calendar", "credential_name": "canvas.feed"},
            )
            check(created.status_code == 201, "POST /integrations -> 201")
            iid = created.json()["id"]
            items_url = f"/integrations/{iid}/items"
            wait(
                hub,
                "the schedule synced 2 events in the background",
                lambda: len(hub.get(items_url).json()) == 2,
            )

            state["body"] = calendar(("a", "Lab 3 (moved)"), ("b", "Quiz 2"), ("c", "Final"))
            manual = hub.post(f"/integrations/{iid}/sync")
            check(manual.status_code == 202, "POST /integrations/{id}/sync -> 202")
            manual_job = manual.json()["job_id"]
            wait(
                hub,
                "that manual sync job succeeded",
                lambda: hub.get(f"/jobs/{manual_job}").json()["status"] == "succeeded",
            )
            wait(
                hub,
                "a manual sync added 1 and updated 1, without duplicates",
                lambda: (
                    sorted(i["title"] for i in hub.get(items_url).json())
                    == ["Final", "Lab 3 (moved)", "Quiz 2"]
                ),
            )

            state["status"] = 500
            failing = hub.post(f"/integrations/{iid}/sync")
            check(failing.status_code == 202, "a second manual sync is queued")
            failing_job = failing.json()["job_id"]
            wait(
                hub,
                "the failing sync job is queued again for a retry",
                lambda: (
                    hub.get(f"/jobs/{failing_job}").json()["attempts"] >= 1
                    and hub.get(f"/jobs/{failing_job}").json()["status"] == "queued"
                ),
            )
            wait(
                hub,
                "a failing feed shows status error",
                lambda: hub.get(f"/integrations/{iid}").json()["status"] == "error",
            )
            shown = hub.get(f"/integrations/{iid}").text + hub.get("/jobs").text
            check(token not in shown, "the feed token is in no response")
            stored = b"".join(p.read_bytes() for p in hub_dir.glob(f"{DB_FILENAME}*"))
            check(token.encode() not in stored, "the feed token is in no byte of hub.sqlite*")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(token not in hub_log, "the feed token is not in the Hub log")
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
        server.shutdown()
        server.server_close()
        with contextlib.suppress(Exception):
            keyring.delete_password(service, f"{owner}:canvas.feed")


class FakeCanvas:
    """A stand-in Canvas API on 127.0.0.1: two courses, assignments due soon (one missing,
    one submitted), an announcement from yesterday. Answers 401 to any other token."""

    def __init__(self, token: str) -> None:
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlsplit

        self.token = token
        self.title = "Lab 3 实验报告"
        self.quiz_deleted = False  # the teacher deletes Quiz 5
        self.requests = 0
        fake = self

        def answer(path: str, auth: str | None) -> tuple[int, Any]:
            if auth != f"Bearer {fake.token}":
                return 401, {"errors": [{"message": "Invalid access token."}]}
            # Missing work is overdue on real Canvas: due yesterday.
            overdue = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            later = (datetime.now(UTC) + timedelta(days=4)).isoformat()
            yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            route = urlsplit(path).path
            if route == "/api/v1/courses":
                return 200, [{"id": 1, "name": "CIS 22A"}, {"id": 2, "name": "MATH 1B"}]
            if route == "/api/v1/courses/1/assignments":
                return 200, [
                    {
                        "id": 11,
                        "name": fake.title,
                        "due_at": overdue,
                        "points_possible": 20,
                        "html_url": "https://canvas.example.edu/courses/1/assignments/11",
                        "submission": {"workflow_state": "unsubmitted", "missing": True},
                    }
                ]
            if route == "/api/v1/courses/2/assignments":
                if fake.quiz_deleted:
                    return 200, []
                return 200, [
                    {
                        "id": 21,
                        "name": "Quiz 5",
                        "due_at": later,
                        "submission": {"workflow_state": "submitted"},
                    }
                ]
            if route == "/api/v1/announcements":
                return 200, [
                    {
                        "id": 7,
                        "title": "Midterm moved",
                        "message": "<p>Now on <b>Friday</b>.</p>",
                        "posted_at": yesterday,
                        "context_code": "course_1",
                    }
                ]
            return 404, {"errors": [{"message": "not found"}]}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fake.requests += 1
                status, body = answer(self.path, self.headers.get("Authorization"))
                data = _json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()


def verify_canvas(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    import uuid

    import keyring

    token = f"canvastoken-{uuid.uuid4().hex[:20]}"
    canvas = FakeCanvas(token)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "canvas-data"
    os.environ["POS_CREDENTIALS_SERVICE"] = service

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    try:
        with running_hub(hub_dir) as hub:
            put = hub.put("/credentials/canvas.token", json={"secret": token})
            check(put.status_code == 200, "the Canvas token is stored as a credential")
            created = hub.post(
                "/integrations",
                json={
                    "kind": "canvas",
                    "name": "Canvas",
                    "credential_name": "canvas.token",
                    "config": {"base_url": canvas.base},
                },
            )
            check(created.status_code == 201, "POST /integrations (canvas) -> 201")
            iid = created.json()["id"]
            items_url = f"/integrations/{iid}/items"
            wait(
                "the background sync read 2 assignments and 1 announcement",
                lambda: len(hub.get(items_url).json()) == 3,
            )
            items = {i["title"]: i for i in hub.get(items_url).json()}
            lab = items["Lab 3 实验报告"]
            check(
                lab["data"]["missing"] is True and lab["data"]["course"] == "CIS 22A",
                "the assignment knows its course and that it is missing",
            )
            check(items["Midterm moved"]["body"] == "Now on Friday.", "announcement text, no HTML")

            canvas.title = "Lab 3 实验报告 - 延期"
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a manual sync finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            titles = sorted(i["title"] for i in hub.get(items_url).json())
            check(
                titles == ["Lab 3 实验报告 - 延期", "Midterm moved", "Quiz 5"],
                "updated, no duplicate",
            )

            canvas.quiz_deleted = True
            before = len(hub.get(items_url).json())
            for attempt in ("first", "second"):  # removal needs two complete syncs in a row
                job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
                wait(
                    f"the {attempt} sync after the deletion finished",
                    lambda job=job: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
                )
                titles = sorted(i["title"] for i in hub.get(items_url).json())
                if attempt == "first":
                    check("Quiz 5" in titles, "missing once: kept for now")
            check("Quiz 5" not in titles, "missing twice: the deleted quiz was removed here too")
            check(
                len(titles) == before - 1 and "Lab 3 实验报告 - 延期" in titles,
                "everything else is still there",
            )

            canvas.token = "rotated"  # the stored token no longer works
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a refused token shows status error",
                lambda: hub.get(f"/integrations/{iid}").json()["status"] == "error",
            )
            error = hub.get(f"/integrations/{iid}").json()["last_error"]
            check("refused the token" in error, f"the error says why ({error})")
            shown = hub.get(f"/integrations/{iid}").text + hub.get("/jobs").text
            check(token not in shown, "the token is in no response")
            stored = b"".join(p.read_bytes() for p in hub_dir.glob(f"{DB_FILENAME}*"))
            check(token.encode() not in stored, "the token is in no byte of hub.sqlite*")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(token not in hub_log, "the token is not in the Hub log")
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
        canvas.close()
        with contextlib.suppress(Exception):
            keyring.delete_password(service, f"{owner}:canvas.token")


def recent(hours_ago: float) -> str:
    """An IMAP INTERNALDATE this many hours ago."""
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%d-%b-%Y %H:%M:%S +0000")


def fake_mail(
    subject: str, body: str, sender: str = "Canvas 通知 <notifications@instructure.com>"
) -> bytes:
    from email.message import EmailMessage
    from email.utils import format_datetime

    m = EmailMessage()
    m["From"] = sender
    m["To"] = "student@example.com"
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime.now(UTC) - timedelta(hours=1))
    m.set_content(body)
    return m.as_bytes()


def verify_email(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    box = Mailbox(username="student@example.com", password=code)
    box.add(fake_mail("作业提醒 Lab 3 明天截止", "请在明天之前提交。"), received=recent(2))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "email-data"
    os.environ["POS_CREDENTIALS_SERVICE"] = service

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    try:
        with running_hub(hub_dir) as hub:
            put = hub.put("/credentials/mail.code", json={"secret": code})
            check(put.status_code == 200, "the mail authorisation code is stored as a credential")
            config = {
                "host": "127.0.0.1",
                "port": str(imap.port),
                "username": "student@example.com",
                "tls": "off",
            }
            created = hub.post(
                "/integrations",
                json={
                    "kind": "email",
                    "name": "163",
                    "credential_name": "mail.code",
                    "config": config,
                },
            )
            check(created.status_code == 201, "POST /integrations (email) -> 201")
            iid = created.json()["id"]
            items_url = f"/integrations/{iid}/items"
            wait("the background sync read the mail", lambda: len(hub.get(items_url).json()) == 1)
            (first,) = hub.get(items_url).json()
            check(first["body"] == "请在明天之前提交。", "subject and text were read")
            verbs = {c.split(" ", 1)[0] for c in box.commands}
            check("EXAMINE" in verbs and "STORE" not in verbs, "opened read-only, nothing changed")
            check(
                all(
                    "BODY.PEEK" in c
                    for c in box.commands
                    if c.startswith("UID FETCH") and "BODY" in c
                ),
                "fetched without marking as read",
            )
            box.messages[0].seen = True
            box.add(fake_mail("Midterm moved", "Now on Friday"), received=recent(0.5))
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a manual sync finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            check(len(hub.get(items_url).json()) == 2, "only the new mail was added")
            newest = hub.get(
                items_url, params={"order": "desc", "item_type": "email_message"}
            ).json()
            check(
                newest[0]["title"] == "Midterm moved",
                "mail can be listed newest first",
            )
            check(newest[1]["data"]["seen"] is True, "mail read elsewhere shows as read here")
            box.password = "rotated"
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a refused code shows status error",
                lambda: hub.get(f"/integrations/{iid}").json()["status"] == "error",
            )
            check(
                "授权码" in hub.get(f"/integrations/{iid}").json()["last_error"],
                "it says to use the 授权码",
            )
            shown = hub.get(f"/integrations/{iid}").text + hub.get("/jobs").text
            check(code not in shown, "the code is in no response")
            stored = b"".join(p.read_bytes() for p in hub_dir.glob(f"{DB_FILENAME}*"))
            check(code.encode() not in stored, "the code is in no byte of hub.sqlite*")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(code not in hub_log, "the code is not in the Hub log")
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
        imap.close()
        with contextlib.suppress(Exception):
            keyring.delete_password(service, f"{owner}:mail.code")


def verify_today(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    token = f"canvastoken-{uuid.uuid4().hex[:20]}"
    canvas = FakeCanvas(token)
    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    box = Mailbox(username="student@example.com", password=code)
    box.add(fake_mail("作业提醒 Lab 3 明天截止", "请在明天之前提交。"), received=recent(2))
    box.add(fake_mail("Already read", "x"), seen=True, received=recent(1))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "today-data"
    os.environ["POS_CREDENTIALS_SERVICE"] = service
    zone = "America/Los_Angeles"

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    try:
        with running_hub(hub_dir) as hub:
            empty = hub.get("/today", params={"tz": zone})
            check(empty.status_code == 200, "GET /today -> 200 on an empty Hub")
            check(empty.json()["sources"] == 0, "an empty Hub reports no sources")
            check(
                hub.get("/today", params={"tz": "Not/AZone"}).status_code == 422,
                "an unknown time zone is refused",
            )
            local_today = datetime.now(UTC).astimezone(ZoneInfo(zone)).date()
            for title, due in (
                ("交房租", local_today.isoformat()),
                ("还图书馆的书", (local_today - timedelta(days=2)).isoformat()),
            ):
                made = hub.post("/tasks", json={"title": title, "due_date": due})
                check(made.status_code == 201, f"task {title} created")
            hub.put("/credentials/canvas.token", json={"secret": token})
            hub.put("/credentials/mail.code", json={"secret": code})
            sources = [
                ("canvas", "Canvas", "canvas.token", {"base_url": canvas.base}),
                (
                    "email",
                    "163 邮箱",
                    "mail.code",
                    {
                        "host": "127.0.0.1",
                        "port": str(imap.port),
                        "username": "student@example.com",
                        "tls": "off",
                    },
                ),
            ]
            for kind, name, credential, config in sources:
                created = hub.post(
                    "/integrations",
                    json={
                        "kind": kind,
                        "name": name,
                        "credential_name": credential,
                        "config": config,
                    },
                )
                check(created.status_code == 201, f"{kind} connected")

            def today() -> dict[str, Any]:
                return hub.get("/today", params={"tz": zone}).json()

            wait(
                "both sources synced into 今日",
                lambda: today()["unread_mail"] == 1 and len(today()["missing"]) == 2,
            )
            view = today()
            print(f"headline: {view['headline']}", flush=True)
            check(view["timezone"] == zone, "the view is computed in the browser's zone")
            check(
                [e["title"] for e in view["due_today"]] == ["交房租"], "today's task is due today"
            )
            missing = {e["title"]: e["badge"] for e in view["missing"]}
            check(
                missing == {"Lab 3 实验报告": "缺交", "还图书馆的书": "逾期"},
                "missing Canvas work and the overdue task are listed",
            )
            check(
                [e["title"] for e in view["mail"]] == ["作业提醒 Lab 3 明天截止"],
                "only unread mail is listed",
            )
            check(
                [e["title"] for e in view["announcements"]] == ["Midterm moved"],
                "yesterday's announcement is listed",
            )
            check(
                "1 封未读邮件" in view["headline"] and "今天有 1 项截止" in view["headline"],
                "the headline counts deadlines and unread mail",
            )
            check(view["sources"] == 2 and view["problems"] == [], "two healthy sources")

            box.password = "rotated"
            mail_id = next(i["id"] for i in hub.get("/integrations").json() if i["kind"] == "email")
            hub.post(f"/integrations/{mail_id}/sync")
            wait("a failing source shows under problems", lambda: len(today()["problems"]) == 1)
            check(code not in json.dumps(today()), "the code is not in the view")
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
        imap.close()
        canvas.close()
        for name in ("canvas.token", "mail.code"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{name}")


def verify_summaries(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    """ADR 0027 with the real Hub, a fake IMAP server and FakeProvider (no money spent)."""
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    model_key = f"sk-verify-{uuid.uuid4().hex}"
    otp = "482913"
    box = Mailbox(username="student@example.com", password=code)
    box.add(
        fake_mail("CIS 22A Lab 5 截止提醒", "Lab 5 截止 周五 23:59，请在 Canvas 提交。"),
        received=recent(3),
    )
    box.add(fake_mail("网易邮箱验证码", f"您的验证码是 {otp}，10分钟内有效。"), received=recent(2))
    box.add(fake_mail("The Weekly Digest", "Campus news this week."), received=recent(1))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "summaries-data"
    model_log = data_dir.parent / "fake-model.log"
    saved = {
        k: os.environ.get(k)
        for k in (
            "POS_CREDENTIALS_SERVICE",
            "POS_MODEL_PROVIDER",
            "POS_FAKE_MODEL_LOG",
            "POS_AI_BUDGET_USD",
        )
    }
    os.environ.update(
        {
            "POS_CREDENTIALS_SERVICE": service,
            "POS_MODEL_PROVIDER": "fake",
            "POS_FAKE_MODEL_LOG": str(model_log),
        }
    )

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    def summary_jobs_done(hub: httpx.Client) -> int:
        return sum(
            1
            for j in hub.get("/jobs").json()
            if j["kind"] == "summaries.email" and j["status"] == "succeeded"
        )

    def by_title(hub: httpx.Client, iid: str) -> dict[str, dict[str, Any]]:
        items = hub.get(f"/integrations/{iid}/items").json()
        ids = ",".join(i["id"] for i in items)
        summaries = {
            s["item_id"]: s for s in hub.get("/summaries/email", params={"item_ids": ids}).json()
        }
        return {i["title"]: summaries.get(i["id"], {}) for i in items}

    try:
        with running_hub(hub_dir) as hub:
            hub.put("/credentials/mail.code", json={"secret": code})
            created = hub.post(
                "/integrations",
                json={
                    "kind": "email",
                    "name": "163",
                    "credential_name": "mail.code",
                    "config": {
                        "host": "127.0.0.1",
                        "port": str(imap.port),
                        "username": "student@example.com",
                        "tls": "off",
                    },
                },
            )
            iid = created.json()["id"]
            wait(
                "the sync read three mails",
                lambda: len(hub.get(f"/integrations/{iid}/items").json()) == 3,
            )
            wait("a summary run followed the sync", lambda: summary_jobs_done(hub) >= 1)
            s = hub.get("/summaries/status").json()
            check(
                s["blocked"] == "no_key" and s["notice"] == "还没有设置 DeepSeek key",
                f"before the key: blocked={s['blocked']} notice={s['notice']}",
            )
            rows = by_title(hub, iid)
            check(
                rows["网易邮箱验证码"].get("status") == "skipped_sensitive",
                "the OTP mail is skipped before any key exists",
            )
            check(hub.get("/models/usage").json()["calls"] == 0, "no model call without a key")

            hub.put("/credentials/deepseek", json={"secret": model_key})
            before = summary_jobs_done(hub)
            check(hub.post("/summaries/run").status_code == 202, "POST /summaries/run -> 202")
            wait("the requested run finished", lambda: summary_jobs_done(hub) > before)
            rows = by_title(hub, iid)
            ok = [t for t, r in rows.items() if r.get("status") == "ok"]
            check(
                sorted(ok) == ["CIS 22A Lab 5 截止提醒", "The Weekly Digest"],
                f"two mails summarised: {ok}",
            )
            lab = rows["CIS 22A Lab 5 截止提醒"]
            check(lab["action_needed"] and lab["gist"], f"the Lab mail needs action: {lab['gist']}")
            usage = hub.get("/models/usage").json()
            check(
                usage["calls"] == 2 and usage["spent_micro_usd"] > 0,
                f"two model calls recorded, {usage['spent_micro_usd']} micro-USD",
            )

            before = summary_jobs_done(hub)
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a re-sync finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            wait("its summary run finished", lambda: summary_jobs_done(hub) > before)
            check(hub.get("/models/usage").json()["calls"] == 2, "a re-sync adds no model call")
            shown = "".join(
                hub.get(p).text
                for p in ("/summaries/status", "/models/usage", "/credentials", "/jobs")
            )
            check(model_key not in shown, "the DeepSeek key is in no response")

        os.environ["POS_AI_BUDGET_USD"] = "0.000001"
        box.add(fake_mail("Midterm moved", "The midterm moves to Friday."), received=recent(0.5))
        with running_hub(hub_dir) as hub:
            before = summary_jobs_done(hub)
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "the sync after the restart finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            wait("its summary run finished", lambda: summary_jobs_done(hub) > before)
            rows = by_title(hub, iid)
            check(
                rows["Midterm moved"].get("status") == "pending",
                "over the budget, the new mail waits",
            )
            s = hub.get("/summaries/status").json()
            check(s["notice"] == "本月 AI 预算已用完", f"notice: {s['notice']}")
            check(hub.get("/models/usage").json()["calls"] == 2, "no call over the budget")

        sent = model_log.read_text(encoding="utf-8")
        check(sent.count("<email>") == 2, "the fake model received exactly two mails")
        check(otp not in sent, "the OTP never reached the model")
        stored = b"".join(p.read_bytes() for p in hub_dir.glob(f"{DB_FILENAME}*"))
        check(model_key.encode() not in stored, "the key is in no byte of hub.sqlite*")
        import sqlite3

        with contextlib.closing(sqlite3.connect(hub_dir / DB_FILENAME)) as db:
            tables = [
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if r[0] != "synced_item"  # the mailbox copy itself holds the body
            ]
            holders = [
                t
                for t in tables
                if any(otp in " ".join(map(str, row)) for row in db.execute(f'SELECT * FROM "{t}"'))
            ]
        check(not holders, f"the OTP is in no table but synced_item ({len(tables)} checked)")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(
            model_key not in hub_log and otp not in hub_log,
            "neither the key nor the OTP is in the Hub log",
        )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        imap.close()
        for name in ("mail.code", "deepseek"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{name}")


def verify_history(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    """ADR 0031: a mailbox's whole history is read and summarised once, newest first."""
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    box = Mailbox(username="student@example.com", password=code)
    for days in (400, 120, 45):  # history, far older than the first-sync window
        box.add(fake_mail(f"旧邮件 {days} 天前", "旧学期通知。"), received=recent(24 * days))
    box.add(fake_mail("新邮件 今天", "本周作业周五截止。"), received=recent(1))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "history-data"
    saved = {k: os.environ.get(k) for k in ("POS_CREDENTIALS_SERVICE", "POS_MODEL_PROVIDER")}
    os.environ.update({"POS_CREDENTIALS_SERVICE": service, "POS_MODEL_PROVIDER": "fake"})

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 40
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    try:
        with running_hub(hub_dir) as hub:
            hub.put("/credentials/mail.code", json={"secret": code})
            hub.put("/credentials/deepseek", json={"secret": f"sk-verify-{uuid.uuid4().hex}"})
            created = hub.post(
                "/integrations",
                json={
                    "kind": "email",
                    "name": "163",
                    "credential_name": "mail.code",
                    "config": {
                        "host": "127.0.0.1",
                        "port": str(imap.port),
                        "username": "student@example.com",
                        "tls": "off",
                    },
                },
            )
            iid = created.json()["id"]
            items_url = f"/integrations/{iid}/items"
            wait(
                "the first sync read today's mail and all three old mails",
                lambda: len(hub.get(items_url).json()) == 4,
            )

            def summarised() -> list[str]:
                items = hub.get(items_url).json()
                ids = ",".join(i["id"] for i in items)
                done = {
                    s["item_id"]
                    for s in hub.get("/summaries/email", params={"item_ids": ids}).json()
                    if s["status"] == "ok"
                }
                return [i["title"] for i in items if i["id"] in done]

            wait("every mail, old ones included, got one summary", lambda: len(summarised()) == 4)
            calls = hub.get("/models/usage").json()["calls"]
            check(calls == 4, f"one model call per mail ({calls})")
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a second sync finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            check(len(hub.get(items_url).json()) == 4, "history is stored once, not twice")
            time.sleep(2)
            check(hub.get("/models/usage").json()["calls"] == 4, "nothing is summarised twice")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        imap.close()
        for name in ("mail.code", "deepseek"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{name}")


def verify_chat(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    """T-0030: questions about mail, answered from summaries, with the real Hub, a fake IMAP
    server and FakeProvider (no money spent)."""
    import sqlite3
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    model_key = f"sk-verify-{uuid.uuid4().hex}"
    otp = "482913"
    body_sentinel = f"BODY{uuid.uuid4().hex[:10]}"
    question_sentinel = f"Q{uuid.uuid4().hex[:10]}"
    box = Mailbox(username="student@example.com", password=code)
    box.add(
        fake_mail(
            "CIS 22A Lab 5 截止提醒",
            "Lab 5 截止 周五 23:59，请在 Canvas 提交。附加说明在后面。" + body_sentinel,
        ),
        received=recent(3),
    )
    box.add(fake_mail("网易邮箱验证码", f"您的验证码是 {otp}，10分钟内有效。"), received=recent(2))
    box.add(fake_mail("The Weekly Digest", "Campus news this week."), received=recent(1))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "chat-data"
    model_log = data_dir.parent / "fake-model-chat.log"
    names = ("POS_CREDENTIALS_SERVICE", "POS_MODEL_PROVIDER", "POS_FAKE_MODEL_LOG")
    saved = {k: os.environ.get(k) for k in names}
    os.environ.update(
        {
            "POS_CREDENTIALS_SERVICE": service,
            "POS_MODEL_PROVIDER": "fake",
            "POS_FAKE_MODEL_LOG": str(model_log),
        }
    )

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    def statuses(hub: httpx.Client, iid: str) -> dict[str, str]:
        items = hub.get(f"/integrations/{iid}/items").json()
        ids = ",".join(i["id"] for i in items)
        found = {
            s["item_id"]: s["status"]
            for s in hub.get("/summaries/email", params={"item_ids": ids}).json()
        }
        return {i["title"]: found.get(i["id"], "") for i in items}

    try:
        with running_hub(hub_dir) as hub:
            hub.put("/credentials/mail.code", json={"secret": code})
            hub.put("/credentials/deepseek", json={"secret": model_key})
            iid = hub.post(
                "/integrations",
                json={
                    "kind": "email",
                    "name": "163",
                    "credential_name": "mail.code",
                    "config": {
                        "host": "127.0.0.1",
                        "port": str(imap.port),
                        "username": "student@example.com",
                        "tls": "off",
                    },
                },
            ).json()["id"]
            wait(
                "two mails summarised, the code mail skipped",
                lambda: sorted(statuses(hub, iid).values()) == ["ok", "ok", "skipped_sensitive"],
            )
            calls_before = hub.get("/models/usage").json()["calls"]
            r = hub.post(
                "/chat/ask",
                json={
                    "question": f"Canvas 作业什么时候交 {question_sentinel}",
                    "time_zone": "America/Los_Angeles",
                },
                timeout=60,
            )
            check(r.status_code == 200, f"POST /chat/ask -> {r.status_code}")
            answer = r.json()
            check(bool(answer["answer"]), f"an answer: {answer['answer']}")
            items = {i["id"]: i["title"] for i in hub.get(f"/integrations/{iid}/items").json()}
            cited = [c["item"]["id"] for c in answer["cited"]]
            check(bool(cited) and all(c in items for c in cited), f"{len(cited)} real mails cited")
            check(
                "CIS 22A Lab 5 截止提醒" in [items[c] for c in cited],
                "the Canvas mail is among them",
            )
            check(
                answer["considered"] == 2,
                f"two summarised mails considered ({answer['considered']})",
            )
            check(
                hub.get("/models/usage").json()["calls"] == calls_before + 1,
                "exactly one model call for the question",
            )
            r = hub.post("/chat/ask", json={"question": "[fake:500] 问"}, timeout=60)
            check(r.status_code == 502, f"a failed call -> {r.status_code} {r.json()['detail']}")
            hub.delete("/credentials/deepseek")
            r = hub.post("/chat/ask", json={"question": "问"}, timeout=60)
            check(
                r.status_code == 503 and r.headers.get("X-Model-Unavailable") == "no_key",
                f"without a key -> {r.status_code} {r.json()['detail']}",
            )

        sent = model_log.read_text(encoding="utf-8").split("\n---\n")
        chats = [c for c in sent if "<mails>" in c]
        check(len(chats) == 2, f"the fake model got two questions ({len(chats)})")
        check("CIS 22A Lab 5" in chats[0], "the Lab mail's subject was sent")
        check(otp not in chats[0] and "验证码" not in chats[0], "nothing of the code mail was sent")
        check(body_sentinel not in chats[0], "no mail body was sent")
        with contextlib.closing(sqlite3.connect(hub_dir / DB_FILENAME)) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            holders = [
                t
                for t in tables
                if any(
                    question_sentinel in " ".join(map(str, row))
                    for row in db.execute(f'SELECT * FROM "{t}"')
                )
            ]
        check(not holders, f"the question is stored in no table ({len(tables)} checked)")
        hub_log = (hub_dir.parent / f"hub-{hub_dir.name}.log").read_text(encoding="utf-8")
        check(question_sentinel not in hub_log, "nor in the Hub log")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        imap.close()
        for name in ("mail.code", "deepseek"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{name}")


def verify_triage(_client: httpx.Client, data_dir: Path, _args: argparse.Namespace) -> None:
    """T-0035: in-app triage - groups, a batch and its undo, a saved rule that covers new mail
    after a re-sync. Real Hub, fake IMAP, FakeProvider (no money spent)."""
    import uuid

    import keyring

    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    box = Mailbox(username="student@example.com", password=code)
    for i in range(6):
        box.add(
            fake_mail(
                f"Weekly digest {i}", "Jobs this week.", sender="Handshake <jobs@joinhandshake.com>"
            ),
            received=recent(10 + i),
        )
    box.add(fake_mail("CIS 22A Lab 5 截止提醒", "Lab 5 截止 周五 23:59。"), received=recent(3))
    box.add(fake_mail("Already read", "Old news."), seen=True, received=recent(30))
    imap = FakeImapServer(box)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    owner = os.environ.get("POS_OWNER_ID", "local")
    hub_dir = data_dir.parent / "triage-data"
    names = ("POS_CREDENTIALS_SERVICE", "POS_MODEL_PROVIDER")
    saved = {k: os.environ.get(k) for k in names}
    os.environ.update({"POS_CREDENTIALS_SERVICE": service, "POS_MODEL_PROVIDER": "fake"})

    def wait(what: str, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not done():
            if time.monotonic() > deadline:
                check(False, what)
            time.sleep(0.3)
        check(True, what)

    def view(hub: httpx.Client) -> dict[str, Any]:
        return hub.get("/triage").json()

    try:
        with running_hub(hub_dir) as hub:
            hub.put("/credentials/mail.code", json={"secret": code})
            hub.put("/credentials/deepseek", json={"secret": f"sk-verify-{uuid.uuid4().hex}"})
            iid = hub.post(
                "/integrations",
                json={
                    "kind": "email",
                    "name": "163",
                    "credential_name": "mail.code",
                    "config": {
                        "host": "127.0.0.1",
                        "port": str(imap.port),
                        "username": "student@example.com",
                        "tls": "off",
                    },
                },
            ).json()["id"]
            wait(
                "seven unread mails are open and summarised",
                lambda: view(hub)["open_count"] == 7 and view(hub)["unsummarised"] == 0,
            )
            v = view(hub)
            check(sum(g["count"] for g in v["groups"]) == v["open_count"], "group counts add up")
            hs = next((g for g in v["groups"] if g["key"] == "sender:joinhandshake.com"), None)
            check(
                hs is not None and hs["count"] == 6,
                f"Handshake has its own group ({hs and hs['count']})",
            )
            assert hs is not None
            batch = hub.post(
                "/triage/handle", json={"item_ids": hs["item_ids"], "group_key": hs["key"]}
            ).json()
            check(view(hub)["open_count"] == 1, "one click handles the group: 未处理 7 -> 1")
            hub.post(f"/triage/batches/{batch['id']}/undo")
            check(view(hub)["open_count"] == 7, "撤销 puts it back to 7")
            batch = hub.post(
                "/triage/handle",
                json={"item_ids": hs["item_ids"], "group_key": hs["key"], "save_rule": True},
            ).json()
            check(bool(batch["rule_id"]), "the group was saved as a rule (以后也这样)")
            box.add(
                fake_mail(
                    "Weekly digest new", "More jobs.", sender="Handshake <jobs@joinhandshake.com>"
                ),
                received=recent(0.5),
            )
            job = hub.post(f"/integrations/{iid}/sync").json()["job_id"]
            wait(
                "a re-sync finished",
                lambda: hub.get(f"/jobs/{job}").json()["status"] == "succeeded",
            )
            wait(
                "the new mail is summarised",
                lambda: view(hub)["unsummarised"] == 0 and view(hub)["unread_count"] == 8,
            )
            v = view(hub)
            new_rule = [m for m in v["handled"] if m["by"] == "rule"]
            check(
                len(new_rule) == 1 and v["open_count"] == 1,
                f"the rule handles the new Handshake mail by itself (open {v['open_count']})",
            )
            flags = [m.seen for m in box.messages]
            check(
                flags.count(True) == 1 and len(flags) == 9,
                f"the mailbox itself is untouched: still 1 read of 9 ({flags.count(True)})",
            )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        imap.close()
        for name in ("mail.code", "deepseek"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{name}")


COMMANDS: dict[str, Callable[[httpx.Client, Path, argparse.Namespace], None]] = {
    "health": verify_health,
    "crud": verify_crud,
    "roundtrip": verify_roundtrip,
    "memory": verify_memory,
    "agent": verify_agent,
    "jobs": verify_jobs,
    "credentials": verify_credentials,
    "integrations": verify_integrations,
    "canvas": verify_canvas,
    "email": verify_email,
    "today": verify_today,
    "summaries": verify_summaries,
    "history": verify_history,
    "chat": verify_chat,
    "triage": verify_triage,
}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to the ANSI code page
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--audit-out", help="crud: write the audit rows as JSON here")
    parser.add_argument("--manifest-out", help="roundtrip: write the export manifest here")
    args = parser.parse_args()

    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root, ignore_cleanup_errors=True) as tmp:
        data_dir = Path(tmp) / "data"
        try:
            with running_hub(data_dir) as client:
                COMMANDS[args.command](client, data_dir, args)
        except CheckFailed as exc:
            print(f"\nRESULT: FAIL ({exc})")
            return 1
    print(f"\nRESULT: PASS ({args.command})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
