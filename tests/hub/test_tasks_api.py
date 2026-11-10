import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.tasks import service
from packages.contracts.tasks import GoalUpdate
from tools.export_openapi import OUT, openapi_json

KINDS = ["goal", "project", "task", "workspace"]
MISSING_ID = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def post(client: TestClient, kind: str, body: dict[str, Any], **headers: str) -> dict[str, Any]:
    response = client.post(f"/{kind}s", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def make(client: TestClient, kind: str, **fields: Any) -> dict[str, Any]:
    """Create `kind` with the parents it needs."""
    body: dict[str, Any] = {"title": f"a {kind}"}
    if kind == "project":
        body["goal_id"] = make(client, "goal")["id"]
    if kind == "task":
        body["project_id"] = make(client, "project")["id"]
    if kind == "workspace":
        body["task_id"] = make(client, "task")["id"]
        body["urls"] = ["https://example.com"]
    return post(client, kind, {**body, **fields})


def events(client: TestClient, entity_id: str | None = None) -> list[audit.AuditEvent]:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        return audit.list_events(session, "local", entity_id)


@pytest.mark.parametrize("kind", KINDS)
def test_create_get_list_update_delete(client: TestClient, kind: str) -> None:
    created = make(client, kind)
    assert created["version"] == 1
    assert created["owner_id"] == "local"
    assert len(created["id"]) == 26
    url = f"/{kind}s/{created['id']}"

    assert client.get(url).json() == created
    assert created["id"] in [e["id"] for e in client.get(f"/{kind}s").json()]

    updated = client.patch(url, json={"version": 1, "title": "renamed"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "renamed"
    assert updated.json()["version"] == 2
    assert client.get(url).json()["title"] == "renamed"

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_id_is_404(client: TestClient, kind: str) -> None:
    url = f"/{kind}s/{MISSING_ID}"
    assert client.get(url).status_code == 404
    assert client.patch(url, json={"version": 1, "title": "x"}).status_code == 404
    assert client.delete(url).status_code == 404


@pytest.mark.parametrize("kind", KINDS)
def test_invalid_payload_is_422(client: TestClient, kind: str) -> None:
    assert client.post(f"/{kind}s", json={}).status_code == 422
    assert client.post(f"/{kind}s", json={"title": "x", "surprise": 1}).status_code == 422
    created = make(client, kind)
    url = f"/{kind}s/{created['id']}"
    assert client.patch(url, json={"version": 1, "title": ""}).status_code == 422
    assert client.patch(url, json={"title": "no version"}).status_code == 422
    assert client.patch(url, json={"version": 1, "title": None}).status_code == 422
    assert client.get(url).json() == created


@pytest.mark.parametrize("kind", KINDS)
def test_stale_version_is_409(client: TestClient, kind: str) -> None:
    created = make(client, kind)
    url = f"/{kind}s/{created['id']}"
    assert client.patch(url, json={"version": 1, "title": "first"}).status_code == 200
    stale = client.patch(url, json={"version": 1, "title": "second"})
    assert stale.status_code == 409
    assert client.get(url).json()["title"] == "first"


def test_repeated_post_with_same_idempotency_key_returns_original(client: TestClient) -> None:
    first = post(client, "goal", {"title": "once"}, **{"Idempotency-Key": "k-1"})
    again = client.post("/goals", json={"title": "once"}, headers={"Idempotency-Key": "k-1"})
    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first
    assert [g["id"] for g in client.get("/goals").json()] == [first["id"]]
    creates = [e.result for e in events(client) if e.action == "goal.create"]
    assert creates == ["ok", "replayed"]


def test_same_idempotency_key_with_different_body_is_422(client: TestClient) -> None:
    first = post(client, "goal", {"title": "once"}, **{"Idempotency-Key": "k-3"})
    other = client.post("/goals", json={"title": "changed"}, headers={"Idempotency-Key": "k-3"})
    assert other.status_code == 422
    assert "different body" in other.json()["detail"]
    assert [g["id"] for g in client.get("/goals").json()] == [first["id"]]
    assert [e.result for e in events(client) if e.action == "goal.create"] == ["ok", "invalid"]


def test_idempotency_body_match_ignores_key_order_and_explicit_defaults(
    client: TestClient,
) -> None:
    first = post(client, "goal", {"title": "g", "notes": "n"}, **{"Idempotency-Key": "k-4"})
    same = {"notes": "n", "title": "g", "status": "active"}
    again = client.post("/goals", json=same, headers={"Idempotency-Key": "k-4"})
    assert again.status_code == 201
    assert again.json()["id"] == first["id"]


def test_idempotency_key_reused_for_another_kind_is_rejected(client: TestClient) -> None:
    post(client, "goal", {"title": "g"}, **{"Idempotency-Key": "k-2"})
    reused = client.post("/projects", json={"title": "p"}, headers={"Idempotency-Key": "k-2"})
    assert reused.status_code == 422
    assert client.get("/projects").json() == []
    assert [e.result for e in events(client) if e.action == "project.create"] == ["invalid"]


@pytest.mark.parametrize("kind", KINDS)
def test_every_write_creates_one_audit_event(client: TestClient, kind: str) -> None:
    entity = make(client, kind)
    url = f"/{kind}s/{entity['id']}"
    assert client.patch(url, json={"version": 1, "title": "b"}).status_code == 200
    assert client.patch(url, json={"version": 1, "title": "stale"}).status_code == 409
    assert client.patch(url, json={"version": 2, "title": None}).status_code == 422
    assert client.delete(url).status_code == 204

    log = events(client, entity["id"])
    assert [(e.action, e.result) for e in log] == [
        (f"{kind}.create", "ok"),
        (f"{kind}.update", "ok"),
        (f"{kind}.update", "conflict"),
        (f"{kind}.update", "invalid"),
        (f"{kind}.delete", "ok"),
    ]
    assert all(e.actor == "owner:local" and e.entity_type == kind for e in log)


def test_rejected_delete_is_audited(client: TestClient) -> None:
    project = make(client, "project")
    assert client.delete(f"/goals/{project['goal_id']}").status_code == 409
    assert [e.result for e in events(client, project["goal_id"])] == ["ok", "conflict"]


def test_create_audit_records_the_stored_state(client: TestClient) -> None:
    task = make(client, "task", tags=["course:CIS"])
    (created,) = events(client, task["id"])
    assert created.detail["payload"]["execution_mode"] is None
    assert created.detail["stored"]["execution_mode"] == "human_led"


def test_concurrent_update_is_409_and_audited(client: TestClient) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    goal = make(client, "goal")
    actor = service.Actor(owner_id="local")
    kind = service.KINDS["goal"]
    with Session(engine) as slow, Session(engine) as fast:
        service.get(slow, actor, kind, goal["id"])
        service.update(fast, actor, kind, goal["id"], GoalUpdate(version=1, title="fast"))
        with pytest.raises(service.Conflict):
            service.update(slow, actor, kind, goal["id"], GoalUpdate(version=1, title="slow"))
    assert client.get(f"/goals/{goal['id']}").json()["title"] == "fast"
    assert [e.result for e in events(client, goal["id"])] == ["ok", "ok", "conflict"]


def test_duplicate_dependencies_are_stored_once(client: TestClient) -> None:
    first = make(client, "task")
    second = make(client, "task", depends_on=[first["id"], first["id"]])
    assert second["depends_on"] == [first["id"]]


def test_audit_log_stores_secrets_redacted(client: TestClient) -> None:
    notes = "login with token=abc123 then send Authorization: Bearer sk-live-xyz789"
    goal = make(client, "goal", notes=notes)
    client.patch(f"/goals/{goal['id']}", json={"version": 1, "notes": "password: hunter2"})

    stored = json.dumps([e.detail for e in events(client, goal["id"])])
    for secret in ("abc123", "sk-live-xyz789", "hunter2"):
        assert secret not in stored
    assert "token=[REDACTED]" in stored
    assert "Authorization: [REDACTED]" in stored


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("token=abc123", "token=[REDACTED]"),
        ('token="abc123"', 'token="[REDACTED]"'),
        ('{"token": "abc123"}', '{"token": "[REDACTED]"}'),
        ("auth_token=abc123", "auth_token=[REDACTED]"),
        ("client_secret=abc123", "client_secret=[REDACTED]"),
        ("db_password=abc123", "db_password=[REDACTED]"),
        ("password: hunter2", "password: [REDACTED]"),
        ("Authorization: abc123", "Authorization: [REDACTED]"),
        ("Authorization: Bearer abc123xyz", "Authorization: [REDACTED]"),
        ("Authorization: Digest abc123x", "Authorization: [REDACTED]"),
        ("send Bearer sk-live-xyz789", "send Bearer [REDACTED]"),
        ("https://user:abc123@host/x", "https://[REDACTED]@host/x"),
        ("key sk-abc12345678", "key [REDACTED]"),
        ("ghp_abcdefghijklmnop1234", "[REDACTED]"),
        ("AKIAABCDEFGHIJKLMNOP", "[REDACTED]"),
        ("x?token=t1&a=1", "x?token=[REDACTED]&a=1"),
        ("a basic plan", "a basic plan"),
        ('password = "a b c"', 'password = "[REDACTED]"'),
        ("secret: 'x y'", "secret: '[REDACTED]'"),
    ],
)
def test_redact_text_catches_common_secret_shapes(text: str, expected: str) -> None:
    assert audit.redact_text(text) == expected


def test_redact_handles_sensitive_keys_and_nesting() -> None:
    redacted = audit.redact(
        {"api_key": "k", "nested": [{"Authorization": "Basic Zm9v"}], "url": "x?token=t1&a=1"}
    )
    assert redacted == {
        "api_key": "[REDACTED]",
        "nested": [{"Authorization": "[REDACTED]"}],
        "url": "x?token=[REDACTED]&a=1",
    }


def test_cis_course_tasks_default_to_human_led(client: TestClient) -> None:
    assert make(client, "task", tags=["course:CIS"])["execution_mode"] == "human_led"
    assert make(client, "task", tags=["home"])["execution_mode"] == "collaborate"
    explicit = make(client, "task", tags=["course:CIS"], execution_mode="delegate")
    assert explicit["execution_mode"] == "delegate"


def test_task_cannot_be_marked_done_without_evidence(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "t", "status": "done"}).status_code == 409
    task = make(client, "task")
    done = client.patch(f"/tasks/{task['id']}", json={"version": 1, "status": "done"})
    assert done.status_code == 409


def test_references_must_exist_and_block_deletion(client: TestClient) -> None:
    assert client.post("/projects", json={"title": "p", "goal_id": MISSING_ID}).status_code == 422

    project = make(client, "project")
    assert client.delete(f"/goals/{project['goal_id']}").status_code == 409

    first = make(client, "task")
    make(client, "task", depends_on=[first["id"]])
    assert client.delete(f"/tasks/{first['id']}").status_code == 409

    url = f"/tasks/{first['id']}"
    assert client.patch(url, json={"version": 1, "depends_on": [first["id"]]}).status_code == 422


def test_workspace_binds_to_exactly_one_parent(client: TestClient) -> None:
    task = make(client, "task")
    both = {"title": "w", "task_id": task["id"], "project_id": task["project_id"]}
    assert client.post("/workspaces", json=both).status_code == 422
    assert client.post("/workspaces", json={"title": "w"}).status_code == 422


def test_committed_openapi_schema_is_current() -> None:
    assert OUT.read_text(encoding="utf-8") == openapi_json(), (
        "run `uv run python -m tools.export_openapi`"
    )
