"""A complete sync removes what the source deleted; a partial one removes nothing."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.integrations import service
from apps.hub.integrations.canvas import CanvasConnector
from apps.hub.integrations.connectors import SyncError
from tests.hub.support import hub_client
from tests.hub.test_canvas import TOKEN, FakeCanvas, Server
from tests.hub.test_integrations import Feed, calendar, event

OWNER = Actor(owner_id="local", source="test")


@pytest.fixture
def store() -> credentials.MemorySecretStore:
    return credentials.MemorySecretStore()


@pytest.fixture
def client(data_dir: Path, store: credentials.MemorySecretStore) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False), secret_store=store) as c:
        yield c


@pytest.fixture
def feed() -> Iterator[Feed]:
    f = Feed()
    yield f
    f.close()


@pytest.fixture
def canvas() -> Iterator[FakeCanvas]:
    elsewhere = Server(lambda _h: (200, {}, []))
    fake = FakeCanvas(elsewhere.base)
    yield fake
    fake.close()
    elsewhere.close()


def add(client: TestClient, kind: str, secret: str, config: dict[str, str]) -> dict[str, Any]:
    assert client.put("/credentials/src", json={"secret": secret}).status_code == 200
    body = {"kind": kind, "name": "src", "credential_name": "src", "config": config}
    created = client.post("/integrations", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def sync(client: TestClient, store: Any, integration: dict[str, Any]) -> dict[str, int]:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    return service.sync(engine, store, OWNER, integration["id"], datetime.now(UTC))


def ids(client: TestClient, integration: dict[str, Any]) -> set[str]:
    return {i["external_id"] for i in client.get(f"/integrations/{integration['id']}/items").json()}


def test_an_event_that_left_the_feed_is_removed(client: TestClient, feed: Feed, store: Any) -> None:
    integration = add(client, "ics", feed.url, {})
    sync(client, store, integration)
    feed.body = calendar(event("a", "Lab 3"))  # "b" was cancelled
    assert sync(client, store, integration)["removed"] == 0  # missing once: not yet
    assert ids(client, integration) == {"a", "b"}
    assert sync(client, store, integration)["removed"] == 1  # missing twice: gone
    assert ids(client, integration) == {"a"}
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        (last,) = [e for e in audit.list_events(s, "local", integration["id"])][-1:]
    assert last.action == "integration.sync" and last.detail["removed"] == 1
    assert last.detail["removed_items"] == ["calendar_event:b"]
    assert last.detail["removed_truncated"] is False


def test_an_unchanged_feed_removes_nothing(client: TestClient, feed: Feed, store: Any) -> None:
    feed.etag = '"v1"'
    integration = add(client, "ics", feed.url, {})
    sync(client, store, integration)
    feed.body = calendar(event("a", "Lab 3"))  # changed, but the server still says 304
    assert sync(client, store, integration)["removed"] == 0
    assert ids(client, integration) == {"a", "b"}


def test_an_empty_answer_removes_nothing(client: TestClient, feed: Feed, store: Any) -> None:
    integration = add(client, "ics", feed.url, {})
    sync(client, store, integration)
    feed.body = calendar()  # a glitch at the source looks like this
    assert sync(client, store, integration)["removed"] == 0
    assert ids(client, integration) == {"a", "b"}


def test_a_deleted_canvas_assignment_is_removed(
    client: TestClient, canvas: FakeCanvas, store: Any
) -> None:
    integration = add(client, "canvas", TOKEN, {"base_url": canvas.base})
    sync(client, store, integration)
    assert "101:2" in ids(client, integration)
    canvas.reading_deleted = True
    assert sync(client, store, integration)["removed"] == 0
    assert sync(client, store, integration)["removed"] == 1
    assert "101:2" not in ids(client, integration)


def test_a_skipped_course_means_nothing_is_removed(
    client: TestClient, canvas: FakeCanvas, store: Any
) -> None:
    integration = add(client, "canvas", TOKEN, {"base_url": canvas.base})
    sync(client, store, integration)
    canvas.reading_deleted = True
    canvas.mode = "hidden-course"  # one course could not be read this time
    assert sync(client, store, integration)["removed"] == 0
    assert sync(client, store, integration)["removed"] == 0
    assert "101:2" in ids(client, integration)


def test_a_failed_sync_removes_nothing(client: TestClient, canvas: FakeCanvas, store: Any) -> None:
    integration = add(client, "canvas", TOKEN, {"base_url": canvas.base})
    sync(client, store, integration)
    before = ids(client, integration)
    canvas.server.http.shutdown()  # Canvas is unreachable
    canvas.server.http.server_close()
    with pytest.raises(SyncError):
        sync(client, store, integration)
    assert ids(client, integration) == before


def test_a_feed_cut_off_mid_download_removes_nothing(
    client: TestClient, feed: Feed, store: Any
) -> None:
    integration = add(client, "ics", feed.url, {})
    sync(client, store, integration)
    feed.body = calendar(event("a", "Lab 3")).replace("END:VCALENDAR\r\n", "")
    assert sync(client, store, integration)["removed"] == 0
    assert sync(client, store, integration)["removed"] == 0
    assert ids(client, integration) == {"a", "b"}


def test_an_item_that_comes_back_after_one_miss_is_kept(
    client: TestClient, feed: Feed, store: Any
) -> None:
    integration = add(client, "ics", feed.url, {})
    sync(client, store, integration)
    whole = feed.body
    feed.body = calendar(event("a", "Lab 3"))
    sync(client, store, integration)  # "b" missing once
    feed.body = whole
    sync(client, store, integration)  # "b" is back
    feed.body = calendar(event("a", "Lab 3"))
    assert sync(client, store, integration)["removed"] == 0  # a fresh first miss
    assert ids(client, integration) == {"a", "b"}


def test_a_refused_announcement_list_blocks_removal(
    client: TestClient, canvas: FakeCanvas, store: Any
) -> None:
    integration = add(client, "canvas", TOKEN, {"base_url": canvas.base})
    sync(client, store, integration)
    canvas.reading_deleted = True
    canvas.mode = "denied-announcements"
    sync(client, store, integration)
    sync(client, store, integration)
    assert "101:2" in ids(client, integration)


def test_a_canvas_page_that_is_not_a_list_is_an_error(canvas: FakeCanvas) -> None:
    canvas.mode = "object-page"
    with pytest.raises(SyncError, match="other than a list"):
        CanvasConnector().fetch(TOKEN, {}, {"base_url": canvas.base})
