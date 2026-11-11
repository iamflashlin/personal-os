"""Integrations against a real local feed server (ADR 0019)."""

import asyncio
import json
import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.db import DB_FILENAME
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.integrations import service
from apps.hub.integrations.connectors import SyncError
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from apps.hub.jobs import service as jobs
from apps.hub.jobs.worker import JobWorker
from apps.hub.main import job_kinds
from packages.contracts.integrations import IntegrationKind
from packages.contracts.jobs import JobStatus
from tests.hub.support import hub_client

TOKEN = "feedtoken-c2b9f1d0aa"  # what Canvas puts in a private feed URL
OWNER = Actor(owner_id="local", source="test")


def event(uid: str, summary: str, start: str = "20261112T075900Z") -> str:
    return f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\nDTSTART:{start}\r\nEND:VEVENT\r\n"


def calendar(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


class Feed:
    """A calendar feed on 127.0.0.1 whose content, ETag support and failures we control."""

    def __init__(self) -> None:
        self.body = calendar(event("a", "Lab 3"), event("b", "Quiz 2", "20261120T170000Z"))
        self.status = 200
        self.etag: str | None = None
        self.requests: list[dict[str, str]] = []
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                feed.requests.append(dict(self.headers))
                if feed.etag and self.headers.get("If-None-Match") == feed.etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                body = feed.body.encode()
                self.send_response(feed.status)
                self.send_header("Content-Type", "text/calendar")
                if feed.etag:
                    self.send_header("ETag", feed.etag)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/feeds/{TOKEN}.ics"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def feed() -> Iterator[Feed]:
    f = Feed()
    yield f
    f.close()


@pytest.fixture
def store() -> credentials.MemorySecretStore:
    return credentials.MemorySecretStore()


@pytest.fixture
def client(data_dir: Path, store: credentials.MemorySecretStore) -> Iterator[TestClient]:
    settings = Settings(data_dir=data_dir, jobs_enabled=False)
    with hub_client(settings, secret_store=store) as c:
        yield c


def connect(client: TestClient, feed: Feed, name: str = "Canvas calendar") -> dict[str, Any]:
    put = client.put("/credentials/canvas.feed", json={"secret": feed.url})
    assert put.status_code == 200, put.text
    created = client.post(
        "/integrations", json={"kind": "ics", "name": name, "credential_name": "canvas.feed"}
    )
    assert created.status_code == 201, created.text
    return created.json()


def sync(client: TestClient, store: credentials.SecretStore, integration_id: str) -> dict[str, int]:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    return service.sync(engine, store, OWNER, integration_id, datetime.now(UTC))


def items(client: TestClient, integration_id: str) -> list[dict[str, Any]]:
    return client.get(f"/integrations/{integration_id}/items").json()


def test_create_list_get_and_delete(client: TestClient, feed: Feed, store: Any) -> None:
    created = connect(client, feed)
    assert created["status"] == "never_synced" and created["interval_s"] == 900
    assert client.get("/integrations").json() == [created]
    assert client.get(f"/integrations/{created['id']}").json() == created
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        (schedule,) = jobs.list_schedules(s, OWNER)
    assert schedule.kind == f"integrations.sync:{created['id']}"
    assert schedule.interval_s == 900

    sync(client, store, created["id"])
    assert client.delete(f"/integrations/{created['id']}").status_code == 204
    assert client.get("/integrations").json() == []
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        left = s.scalar(
            select(func.count())
            .select_from(SyncedItemRow)
            .where(SyncedItemRow.integration_id == created["id"])
        )
        (deleted,) = [
            e for e in audit.list_events(s, "local", created["id"]) if e.action.endswith("delete")
        ]
    assert left == 0  # the items went with it (ON DELETE CASCADE)
    assert deleted.detail["items_removed"] == 2
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        assert jobs.list_schedules(s, OWNER) == []
    assert client.get("/credentials").json()[0]["name"] == "canvas.feed"  # kept


def test_nothing_is_scheduled_without_an_integration(client: TestClient) -> None:
    assert client.get("/jobs/schedules").json() == []


def test_a_missing_credential_or_unknown_kind_is_refused(client: TestClient) -> None:
    missing = client.post(
        "/integrations", json={"kind": "ics", "name": "x", "credential_name": "not.set"}
    )
    assert missing.status_code == 422
    unknown = client.post(
        "/integrations", json={"kind": "pop3", "name": "x", "credential_name": "not.set"}
    )
    assert unknown.status_code == 422


def test_a_sync_adds_updates_and_never_duplicates(
    client: TestClient, feed: Feed, store: Any
) -> None:
    integration = connect(client, feed)
    assert sync(client, store, integration["id"]) == {"added": 2, "updated": 0, "unchanged": 0}
    first = {i["external_id"]: i for i in items(client, integration["id"])}
    assert first["a"]["title"] == "Lab 3"
    assert first["b"]["starts_at"].startswith("2026-11-20T17:00:00")

    assert sync(client, store, integration["id"]) == {"added": 0, "updated": 0, "unchanged": 2}
    again = {i["external_id"]: i for i in items(client, integration["id"])}
    assert again == first  # same versions, same timestamps: nothing was rewritten

    feed.body = calendar(
        event("a", "Lab 3 (moved)"), event("b", "Quiz 2", "20261120T170000Z"), event("c", "Final")
    )
    assert sync(client, store, integration["id"]) == {"added": 1, "updated": 1, "unchanged": 1}
    final = {i["external_id"]: i for i in items(client, integration["id"])}
    assert final["a"]["title"] == "Lab 3 (moved)" and final["a"]["version"] == 2
    assert final["b"] == first["b"]
    assert client.get(f"/integrations/{integration['id']}").json()["item_count"] == 3


def test_an_unchanged_feed_answers_304_and_writes_nothing(
    client: TestClient, feed: Feed, store: Any
) -> None:
    feed.etag = '"v1"'
    integration = connect(client, feed)
    sync(client, store, integration["id"])
    before = items(client, integration["id"])
    assert sync(client, store, integration["id"]) == {"added": 0, "updated": 0, "unchanged": 0}
    assert feed.requests[-1].get("If-None-Match") == '"v1"'
    assert items(client, integration["id"]) == before


def test_items_can_be_filtered_by_time(client: TestClient, feed: Feed, store: Any) -> None:
    integration = connect(client, feed)
    sync(client, store, integration["id"])
    window = {"start": "2026-11-15T00:00:00Z", "end": "2026-11-30T00:00:00Z"}
    found = client.get(f"/integrations/{integration['id']}/items", params=window).json()
    assert [i["external_id"] for i in found] == ["b"]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, "oops", "HTTP 500"),
        (200, "<html>please log in</html>", "not an iCalendar"),
    ],
)
def test_a_failing_feed_sets_an_error_without_the_secret_url(
    client: TestClient,
    feed: Feed,
    store: Any,
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
    status: int,
    body: str,
    expected: str,
) -> None:
    integration = connect(client, feed)
    feed.status, feed.body = status, body
    with caplog.at_level(logging.DEBUG), pytest.raises(SyncError):
        sync(client, store, integration["id"])
    after = client.get(f"/integrations/{integration['id']}").json()
    assert after["status"] == "error" and expected in after["last_error"]
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        logged = json.dumps([e.model_dump(mode="json") for e in audit.list_events(s, "local")])
    stored = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    for where in (json.dumps(after), logged, caplog.text):
        assert TOKEN not in where
    assert TOKEN.encode() not in stored


def test_an_unreachable_feed_is_an_error_too(client: TestClient, store: Any) -> None:
    client.put("/credentials/dead.feed", json={"secret": f"http://127.0.0.1:9/{TOKEN}.ics"})
    created = client.post(
        "/integrations", json={"kind": "ics", "name": "x", "credential_name": "dead.feed"}
    ).json()
    with pytest.raises(SyncError, match="could not be reached"):
        sync(client, store, created["id"])
    assert TOKEN not in client.get(f"/integrations/{created['id']}").json()["last_error"]


def test_the_scheduled_job_syncs_and_a_failing_one_is_retried(
    client: TestClient, feed: Feed, store: credentials.MemorySecretStore
) -> None:
    integration = connect(client, feed)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    worker = JobWorker(engine, "local", job_kinds(store, "local"))
    asyncio.run(worker.tick())  # the schedule is due at once
    assert len(items(client, integration["id"])) == 2

    feed.status = 503
    job_id = client.post(f"/integrations/{integration['id']}/sync").json()["job_id"]
    asyncio.run(worker.tick())
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == JobStatus.queued and job["attempts"] == 1  # will retry
    assert "HTTP 503" in job["last_error"] and TOKEN not in job["last_error"]


def test_integrations_belong_to_their_owner(client: TestClient, feed: Feed) -> None:
    integration = connect(client, feed)
    other = Actor(owner_id="someone-else")
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        assert service.list_all(s, other) == []
        with pytest.raises(Exception, match="not found"):
            service.get(s, other, integration["id"])


def test_create_sync_and_delete_are_audited(client: TestClient, feed: Feed, store: Any) -> None:
    integration = connect(client, feed)
    sync(client, store, integration["id"])
    client.delete(f"/integrations/{integration['id']}")
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        actions = [e.action for e in audit.list_events(s, "local", integration["id"])]
    assert actions == ["integration.create", "integration.sync", "integration.delete"]


@pytest.mark.parametrize(
    "secret",
    [
        f"http://127.0.0.1:9/feeds/{TOKEN} x.ics",  # pasted with a space
        f"http://127.0.0.1:9/feeds/{TOKEN}\n.ics",  # wrapped by an email client
    ],
    ids=["space", "line-break"],  # test ids must not print secret-shaped URLs
)
def test_a_mangled_feed_url_never_reaches_the_error(
    client: TestClient, store: Any, caplog: pytest.LogCaptureFixture, secret: str
) -> None:
    client.put("/credentials/pasted.feed", json={"secret": secret})
    created = client.post(
        "/integrations", json={"kind": "ics", "name": "x", "credential_name": "pasted.feed"}
    ).json()
    with caplog.at_level(logging.DEBUG), pytest.raises(SyncError, match="paste it again"):
        sync(client, store, created["id"])
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        logged = json.dumps([e.model_dump(mode="json") for e in audit.list_events(s, "local")])
    shown = client.get(f"/integrations/{created['id']}").text
    for where in (shown, logged, caplog.text):
        assert TOKEN not in where


def test_an_unexpected_error_keeps_only_its_type(
    client: TestClient, feed: Feed, store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Leaky:
        def fetch(self, secret: str, cursor: Any) -> Any:
            raise RuntimeError(f"library bug while reading {secret}")

    integration = connect(client, feed)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    connectors = {IntegrationKind.ics: Leaky()}
    with pytest.raises(SyncError) as raised:
        service.sync(engine, store, OWNER, integration["id"], datetime.now(UTC), connectors)
    assert TOKEN not in str(raised.value)
    after = client.get(f"/integrations/{integration['id']}").json()
    assert after["last_error"] == "sync failed (RuntimeError)"


def test_a_redirect_to_another_scheme_is_refused(client: TestClient, store: Any) -> None:
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"ftp://example.com/{TOKEN}.ics")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/feed.ics"
        client.put("/credentials/redirecting", json={"secret": url})
        created = client.post(
            "/integrations", json={"kind": "ics", "name": "x", "credential_name": "redirecting"}
        ).json()
        with pytest.raises(SyncError, match="unsupported address"):
            sync(client, store, created["id"])
    finally:
        server.shutdown()
        server.server_close()


def test_two_long_uids_that_differ_late_stay_two_items(
    client: TestClient, feed: Feed, store: Any
) -> None:
    long_a, long_b = "u" * 600 + "a", "u" * 600 + "b"
    feed.body = calendar(event(long_a, "one"), event(long_b, "two"))
    integration = connect(client, feed)
    assert sync(client, store, integration["id"])["added"] == 2


def test_an_orphan_schedule_removes_itself(
    client: TestClient, feed: Feed, store: credentials.MemorySecretStore
) -> None:
    integration = connect(client, feed)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as s:  # the integration vanished, its schedule did not
        s.execute(delete(IntegrationRow).where(IntegrationRow.id == integration["id"]))
        s.commit()
    asyncio.run(JobWorker(engine, "local", job_kinds(store, "local")).tick())
    with Session(engine) as s:
        assert jobs.list_schedules(s, OWNER) == []


def test_startup_gives_back_a_missing_schedule(
    data_dir: Path, feed: Feed, store: credentials.MemorySecretStore
) -> None:
    settings = Settings(data_dir=data_dir, jobs_enabled=False)
    with hub_client(settings, secret_store=store) as client:
        integration = connect(client, feed)
        with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
            jobs.delete_schedule(s, OWNER, f"integrations.sync:{integration['id']}")
    with hub_client(settings, secret_store=store) as client:
        kinds = [k["kind"] for k in client.get("/jobs/schedules").json()]
    assert kinds == [f"integrations.sync:{integration['id']}"]


def test_only_registered_families_route_by_prefix() -> None:
    kinds = job_kinds(credentials.MemorySecretStore(), "local")
    assert kinds.get("integrations.sync:01ABC") is not None
    assert kinds.get("system.noop:anything") is None
