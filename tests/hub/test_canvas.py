"""The Canvas connector against a local stand-in Canvas server (ADR 0020)."""

import json
import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.db import DB_FILENAME
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.integrations import canvas as canvas_module
from apps.hub.integrations import service
from apps.hub.integrations.canvas import (
    CanvasConnector,
    _Client,
    _origin,
    _SameOriginOnly,
    _strip_html,
    canvas_base_url,
)
from apps.hub.integrations.connectors import SyncError
from tests.hub.support import hub_client

TOKEN = "canvastoken-7Hq2Lr9WxY"
OWNER = Actor(owner_id="local", source="test")


class Server:
    """A tiny HTTP server whose answers a test function decides."""

    def __init__(self, answer: Any) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append((self.path, dict(self.headers)))
                status, headers, body = answer(self)
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
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


class FakeCanvas:
    """Two courses (the second on page 2), assignments and an announcement."""

    def __init__(self, elsewhere: str | None = None) -> None:
        self.mode = "normal"  # or: redirect-away, next-away, relative-next, hidden-course
        self.elsewhere = elsewhere
        self.assignment_title = "Lab 3 实验报告"
        self.reading_deleted = False  # the teacher deleted the "Reading" assignment
        self.material_deleted = False  # the teacher removed every module item
        self.server = Server(self.answer)
        self.base = self.server.base

    def answer(self, h: BaseHTTPRequestHandler) -> tuple[int, dict[str, str], Any]:
        if h.headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {}, {"errors": [{"message": "Invalid access token."}]}
        url = urlsplit(h.path)
        query = parse_qs(url.query)
        if url.path == "/api/v1/courses/202/assignments" and self.mode == "object-page":
            return 200, {}, {"status": "under maintenance"}
        if url.path == "/api/v1/courses":
            if self.mode == "redirect-away":
                return 302, {"Location": f"{self.elsewhere}/api/v1/courses"}, None
            if query.get("page") == ["2"]:
                return 200, {}, [{"id": 202, "name": "MATH 1B", "course_code": "MATH-1B"}]
            nxt = f"{self.elsewhere if self.mode == 'next-away' else self.base}"
            if self.mode == "relative-next":
                nxt = ""
            link = f'<{nxt}/api/v1/courses?page=2&per_page=100>; rel="next"'
            assert query.get("include[]") == ["total_scores"]
            first = [
                {
                    "id": 101,
                    "name": "CIS 22A",
                    "course_code": "CIS-22A",
                    "apply_assignment_group_weights": True,
                    "enrollments": [
                        {
                            "type": "student",
                            "computed_current_score": 93.5,
                            "computed_current_grade": "A",
                            "computed_final_score": 41.0,
                        }
                    ],
                }
            ]
            if self.mode == "hidden-course":
                first.append({"id": 303, "name": "Hidden"})
            first += [{"id": "not-a-number", "name": "Broken"}, {"id": 404, "course_code": "PE-1"}]
            return 200, {"Link": link}, first
        if url.path == "/api/v1/courses/101/assignment_groups":
            return (
                200,
                {},
                [
                    {"id": 11, "name": " Labs ", "group_weight": 60},
                    {"id": 12, "name": "Exams", "group_weight": 40.0},
                    {"id": "bad", "name": "Broken"},
                ],
            )
        if url.path == "/api/v1/courses/101/modules":
            assert query.get("include[]") == ["items"]
            return (
                200,
                {},
                [
                    {
                        "id": 1,
                        "name": "Week 1",
                        "position": 1,
                        "items": [
                            {
                                "id": 501,
                                "type": "File",
                                "title": "Syllabus.pdf",
                                "position": 1,
                                "html_url": "https://school.instructure.com/courses/101/modules/items/501",
                            },
                            {
                                "id": 502,
                                "type": "Page",
                                "title": "Notes",
                                "position": 2,
                                "html_url": "https://school.instructure.com/courses/101/modules/items/502",
                            },
                            {"id": 503, "type": "Assignment", "title": "Lab 1"},
                            {"id": 504, "type": "SubHeader", "title": "Readings"},
                            "not-an-item",
                        ],
                    },
                    # Canvas leaves out `items` for a big module and sends only items_url.
                    {
                        "id": 2,
                        "name": "Week 2",
                        "position": 2,
                        "items_count": 40,
                        "items_url": "https://school.instructure.com/api/v1/courses/101/modules/2/items",
                    },
                ]
                if not self.material_deleted
                else [
                    {"id": 1, "name": "Week 1", "position": 1, "items": []},
                    {"id": 2, "name": "Week 2", "position": 2, "items": []},
                ],
            )
        if url.path in (
            "/api/v1/courses/202/assignment_groups",
            "/api/v1/courses/404/assignment_groups",
        ):
            if self.mode == "hidden-groups" and "202" in url.path:
                return 403, {}, {"errors": [{"message": "unauthorized"}]}
            return 200, {}, []
        if url.path == "/api/v1/courses/404/modules":
            return 200, {}, []
        if url.path == "/api/v1/courses/101/modules/2/items":
            return (
                200,
                {},
                [
                    {
                        "id": 601,
                        "type": "File",
                        "title": "Big module file",
                        "position": 1,
                        "html_url": "https://school.instructure.com/courses/101/modules/items/601",
                    }
                ],
            )
        if url.path == "/api/v1/courses/202/modules":
            if self.mode == "hidden-modules":
                return 403, {}, {"errors": [{"message": "unauthorized"}]}
            return 200, {}, []
        if url.path == "/api/v1/courses/101/assignments":
            assert query.get("include[]") == ["submission"]
            return (
                200,
                {},
                [
                    {
                        "id": 1,
                        "name": self.assignment_title,
                        "due_at": "2026-11-01T07:59:00Z",
                        "points_possible": 20,
                        "html_url": "https://school.instructure.com/courses/101/assignments/1",
                        "assignment_group_id": 11,
                        "omit_from_final_grade": True,
                        "submission": {"workflow_state": "unsubmitted", "missing": True},
                    },
                    *(
                        []
                        if self.reading_deleted
                        else [{"id": 2, "name": "Reading", "due_at": None, "submission": {}}]
                    ),
                ],
            )
        if url.path == "/api/v1/courses/303/assignments":
            return 401, {}, {"errors": [{"message": "user not authorized to perform that action"}]}
        if url.path == "/api/v1/courses/404/assignments":
            return 200, {}, [{"id": 5, "name": "Swim", "submission": ["odd", "shape"]}]
        if url.path == "/api/v1/courses/202/assignments":
            return (
                200,
                {},
                [
                    {
                        "id": 9,
                        "name": "Quiz 5",
                        "due_at": "2026-11-20T17:00:00Z",
                        "submission": {
                            "workflow_state": "graded",
                            "score": 9.5,
                            "grade": "A",
                            "graded_at": "2026-11-10T01:00:00Z",
                            "excused": False,
                        },
                    }
                ],
            )
        if url.path == "/api/v1/announcements" and self.mode == "denied-announcements":
            return 403, {}, {"errors": [{"message": "user not authorized"}]}
        if url.path == "/api/v1/announcements":
            assert {"course_101", "course_202"} <= set(query["context_codes[]"])
            # Canvas ends the window 28 days after start_date unless end_date is given.
            assert query["end_date"][0] >= datetime.now(UTC).date().isoformat()
            assert query["start_date"][0] < query["end_date"][0]
            return (
                200,
                {},
                [
                    {
                        "id": 77,
                        "title": "Midterm moved",
                        "message": "<p>The midterm is now on <b>Friday</b> &amp; open book.</p>",
                        "posted_at": "2026-11-09T18:00:00Z",
                        "context_code": "course_101",
                        "html_url": "https://school.instructure.com/courses/101/announcements/77",
                    }
                ],
            )
        return 404, {}, {"errors": [{"message": "not found"}]}

    def close(self) -> None:
        self.server.close()


@pytest.fixture
def elsewhere() -> Iterator[Server]:
    other = Server(lambda _h: (200, {}, []))
    yield other
    other.close()


@pytest.fixture
def canvas(elsewhere: Server) -> Iterator[FakeCanvas]:
    fake = FakeCanvas(elsewhere.base)
    yield fake
    fake.close()


@pytest.fixture
def store() -> credentials.MemorySecretStore:
    return credentials.MemorySecretStore()


@pytest.fixture
def client(data_dir: Path, store: credentials.MemorySecretStore) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False), secret_store=store) as c:
        yield c


def fetch(canvas: FakeCanvas, token: str = TOKEN) -> dict[str, Any]:
    batch = CanvasConnector().fetch(token, {}, {"base_url": canvas.base})
    assert batch.items is not None
    return {f"{i.item_type}/{i.external_id}": i for i in batch.items}


def connect(client: TestClient, canvas: FakeCanvas, token: str = TOKEN) -> dict[str, Any]:
    assert client.put("/credentials/canvas.token", json={"secret": token}).status_code == 200
    created = client.post(
        "/integrations",
        json={
            "kind": "canvas",
            "name": "School Canvas",
            "credential_name": "canvas.token",
            "config": {"base_url": canvas.base + "/some/page"},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def sync(client: TestClient, store: Any, integration: dict[str, Any]) -> dict[str, int]:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    return service.sync(engine, store, OWNER, integration["id"], datetime.now(UTC))


def test_courses_assignments_and_announcements_are_read(canvas: FakeCanvas) -> None:
    items = fetch(canvas)
    assert sorted(items) == [
        "canvas_announcement/77",
        "canvas_assignment/101:1",
        "canvas_assignment/101:2",
        "canvas_assignment/202:9",
        "canvas_assignment/404:5",  # a course with only a code; a non-numeric id is skipped
        "canvas_course/101",
        "canvas_course/202",
        "canvas_course/404",  # no groups (404): still a course, with none
        "canvas_material/101:501",
        "canvas_material/101:502",
        "canvas_material/101:601",  # from a big module's items_url
    ]
    assert items["canvas_assignment/404:5"].data["course"] == "PE-1"
    assert items["canvas_assignment/404:5"].data["submission_state"] == ""  # odd shape
    lab = items["canvas_assignment/101:1"]
    assert lab.title == "Lab 3 实验报告"
    assert lab.starts_at == datetime(2026, 11, 1, 7, 59, tzinfo=UTC)
    assert lab.data["course"] == "CIS 22A" and lab.data["points_possible"] == 20
    assert lab.data["missing"] is True and lab.data["submission_state"] == "unsubmitted"
    assert items["canvas_assignment/101:2"].starts_at is None  # no due date
    assert items["canvas_assignment/202:9"].data["score"] == 9.5  # course from page 2
    news = items["canvas_announcement/77"]
    assert news.body == "The midterm is now on Friday & open book."
    assert news.data["course"] == "CIS 22A"


def test_the_token_goes_only_to_canvas(canvas: FakeCanvas, elsewhere: Server) -> None:
    fetch(canvas)
    assert canvas.server.requests  # it was used
    assert all(h.get("Authorization") == f"Bearer {TOKEN}" for _p, h in canvas.server.requests)
    assert elsewhere.requests == []


@pytest.mark.parametrize("mode", ["redirect-away", "next-away"])
def test_a_redirect_or_next_link_to_another_site_is_refused(
    canvas: FakeCanvas, elsewhere: Server, mode: str
) -> None:
    canvas.mode = mode
    with pytest.raises(SyncError, match="elsewhere"):
        fetch(canvas)
    assert elsewhere.requests == []  # the token never left


def test_a_refused_token_says_so_without_the_token(canvas: FakeCanvas) -> None:
    with pytest.raises(SyncError, match="refused the token") as raised:
        fetch(canvas, token="wrong-token")
    assert "wrong-token" not in str(raised.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://school.instructure.com/", "https://school.instructure.com"),
        ("  https://School.Instructure.com/courses/1 ", "https://school.instructure.com"),
        ("http://127.0.0.1:8080/x", "http://127.0.0.1:8080"),
        ("https://school.instructure.com:443/", "https://school.instructure.com"),
        ("https://school.instructure.com:8443", "https://school.instructure.com:8443"),
    ],
)
def test_the_canvas_address_is_normalised(raw: str, expected: str) -> None:
    assert canvas_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://school.instructure.com",
        "school",
        "ftp://x",
        "",
        "https://me:pw@school.instructure.com",  # config is shown and audited: no secrets
    ],
)
def test_a_bad_canvas_address_is_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        canvas_base_url(raw)


def test_through_the_hub_a_resync_updates_without_duplicates(
    client: TestClient, canvas: FakeCanvas, store: Any
) -> None:
    integration = connect(client, canvas)
    assert integration["config"] == {"base_url": canvas.base}
    assert sync(client, store, integration) == {
        "added": 11,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
    }
    canvas.assignment_title = "Lab 3 实验报告 - 延期"
    assert sync(client, store, integration) == {
        "added": 0,
        "updated": 1,
        "unchanged": 10,
        "removed": 0,
    }
    titles = {i["title"] for i in client.get(f"/integrations/{integration['id']}/items").json()}
    assert "Lab 3 实验报告 - 延期" in titles and len(titles) == 11


@pytest.mark.parametrize(
    "config",
    [
        {},  # no address
        {"base_url": "http://school.instructure.com"},  # not https
        {"base_url": "https://school.instructure.com", "token": "x"},  # secrets are not config
    ],
)
def test_bad_canvas_settings_are_refused(client: TestClient, config: dict[str, str]) -> None:
    client.put("/credentials/canvas.token", json={"secret": TOKEN})
    body = {"kind": "canvas", "name": "x", "credential_name": "canvas.token", "config": config}
    assert client.post("/integrations", json=body).status_code == 422


def test_a_calendar_feed_takes_no_settings(client: TestClient) -> None:
    client.put("/credentials/feed", json={"secret": "https://x/f.ics"})
    body = {"kind": "ics", "name": "x", "credential_name": "feed", "config": {"a": "b"}}
    assert client.post("/integrations", json=body).status_code == 422


def test_a_wrong_token_leaves_no_trace_of_itself(
    client: TestClient,
    canvas: FakeCanvas,
    store: Any,
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    integration = connect(client, canvas, token="canvastoken-WRONG-abc123")
    with caplog.at_level(logging.DEBUG), pytest.raises(SyncError, match="refused the token"):
        sync(client, store, integration)
    after = client.get(f"/integrations/{integration['id']}").json()
    assert after["status"] == "error" and "HTTP 401" in after["last_error"]
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        logged = json.dumps([e.model_dump(mode="json") for e in audit.list_events(s, "local")])
    stored = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    for where in (json.dumps(after), logged, caplog.text):
        assert "canvastoken-WRONG-abc123" not in where
    assert b"canvastoken-WRONG-abc123" not in stored


def test_announcement_html_becomes_readable_text() -> None:
    assert _strip_html("<p>Now on <b>Friday</b>.</p><p>Bring a pen&amp;paper!</p>") == (
        "Now on Friday. Bring a pen&paper!"
    )
    assert _strip_html("line<br>break<li>item</li>") == "line break item"


@pytest.mark.parametrize("via", ["next-link", "redirect"])
def test_the_token_never_travels_over_plain_http(via: str, monkeypatch: pytest.MonkeyPatch) -> None:
    base = "https://school.instructure.com"
    downgraded = "http://school.instructure.com/api/v1/courses?page=2"
    if via == "redirect":
        handler = _SameOriginOnly(_origin(base))
        with pytest.raises(SyncError, match="elsewhere"):
            handler.redirect_request(None, None, 302, "Found", {}, downgraded)
        return
    client = _Client(base, TOKEN)
    calls: list[str] = []

    def fake_get(url: str) -> tuple[Any, str | None]:
        calls.append(url)
        return [{"id": 1, "name": "x"}], f'<{downgraded}>; rel="next"'

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(SyncError, match="elsewhere"):
        list(client.pages("/api/v1/courses", {}))
    assert calls == [f"{base}/api/v1/courses?"]  # the http page was never requested


def test_a_relative_next_link_is_followed(canvas: FakeCanvas) -> None:
    canvas.mode = "relative-next"
    assert "canvas_assignment/202:9" in fetch(canvas)


def test_one_hidden_course_is_skipped_not_fatal(canvas: FakeCanvas) -> None:
    canvas.mode = "hidden-course"
    batch = CanvasConnector().fetch(TOKEN, {}, {"base_url": canvas.base})
    assert batch.items is not None
    assert any(i.external_id == "202:9" for i in batch.items)  # other courses still synced
    assert batch.cursor["skipped_resources"] == 1


def test_too_many_pages_is_an_error_not_a_silent_cut(
    canvas: FakeCanvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canvas_module, "MAX_PAGES", 1)
    with pytest.raises(SyncError, match="more than 1 pages"):
        fetch(canvas)


def test_scripts_and_styles_are_not_announcement_text() -> None:
    text = "<style>p{color:red}</style><p>Hello</p><script>alert(1)</script>"
    assert _strip_html(text) == "Hello"


def test_migration_0009_keeps_existing_integrations_working(tmp_path: Path) -> None:
    from alembic import command

    from apps.hub.core.db import _alembic_config, make_engine, upgrade_to_head

    engine = make_engine(tmp_path)
    cfg = _alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0008")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO integration (id, owner_id, created_at, updated_at, source, version, "
            "kind, name, credential_name, interval_s, status, last_error, cursor) VALUES "
            "('01JX0000000000000000000000', 'local', '2026-11-10 00:00:00', "
            "'2026-11-10 00:00:00', 'test', 1, 'ics', 'old feed', 'feed', 900, "
            "'never_synced', '', '{}')"
        )
    upgrade_to_head(engine)
    engine.dispose()
    with hub_client(Settings(data_dir=tmp_path, jobs_enabled=False)) as client:
        (old,) = client.get("/integrations").json()
    assert old["name"] == "old feed" and old["config"] == {}


def test_courses_groups_scores_and_materials_are_read(canvas: FakeCanvas) -> None:
    canvas.mode = "hidden-modules"
    batch = CanvasConnector().fetch(TOKEN, {}, {"base_url": canvas.base})
    by_type: dict[str, list[Any]] = {}
    assert batch.items is not None
    for item in batch.items:
        by_type.setdefault(item.item_type, []).append(item)
    course = next(c for c in by_type["canvas_course"] if c.external_id == "101")
    assert course.title == "CIS 22A"
    assert course.data["current_score"] == 93.5 and course.data["current_grade"] == "A"
    assert course.data["final_score"] == 41.0 and course.data["weighted"] is True
    assert course.data["groups"] == [
        {"id": 11, "name": "Labs", "weight": 60.0},
        {"id": 12, "name": "Exams", "weight": 40.0},
    ]
    materials = {m.title: m for m in by_type["canvas_material"]}
    # assignments and headers are not materials; a big module's items are read too
    assert set(materials) == {"Syllabus.pdf", "Notes", "Big module file"}
    assert materials["Notes"].url.endswith("/modules/items/502")
    assert course.url == f"{canvas.base}/courses/101"
    assert materials["Syllabus.pdf"].data["module"] == "Week 1"
    assert materials["Syllabus.pdf"].data["kind"] == "File"
    lab = next(a for a in by_type["canvas_assignment"] if a.external_id == "101:1")
    assert lab.data["group_id"] == 11 and lab.data["missing"] is True
    # course 202 hides its modules: its materials are unknown, so nothing is pruned
    assert batch.complete is False


def test_new_assignment_fields_are_kept(canvas: FakeCanvas) -> None:
    items = fetch(canvas)
    quiz = items["canvas_assignment/202:9"].data
    assert quiz["grade"] == "A" and quiz["graded_at"] == "2026-11-10T01:00:00Z"
    assert quiz["excused"] is False
    assert items["canvas_assignment/101:1"].data["omit_from_final"] is True


def test_hidden_groups_keep_the_course_with_unknown_groups(canvas: FakeCanvas) -> None:
    canvas.mode = "hidden-groups"
    batch = CanvasConnector().fetch(TOKEN, {}, {"base_url": canvas.base})
    assert batch.items is not None and batch.complete is False
    course = next(
        i for i in batch.items if i.item_type == "canvas_course" and i.external_id == "202"
    )
    assert course.data["groups"] is None and course.title == "MATH 1B"


def test_materials_are_pruned_only_after_complete_syncs(
    client: TestClient, canvas: FakeCanvas, store: Any
) -> None:
    integration = connect(client, canvas)
    sync(client, store, integration)
    canvas.material_deleted = True
    canvas.mode = "hidden-modules"  # a refused module list: nothing may be removed
    assert sync(client, store, integration)["removed"] == 0
    canvas.mode = "normal"
    sync(client, store, integration)  # the first complete sync without them
    removed = sync(client, store, integration)["removed"]  # the second removes them
    assert removed == 3
