from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.settings import Settings
from tests.hub.support import hub_client


def new_task(client: TestClient, **fields: Any) -> dict[str, Any]:
    response = client.post("/tasks", json={"title": "Read lab 3 handout", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def audit_results(client: TestClient, task_id: str) -> list[tuple[str, str]]:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        return [(e.action, e.result) for e in audit.list_events(session, "local", task_id)]


def test_complete_marks_done_with_one_evidence_row_and_one_audit_event(
    client: TestClient,
) -> None:
    task = new_task(client)
    done = client.post(f"/tasks/{task['id']}/complete", json={"version": 1, "note": "read it"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["version"] == 2

    evidence = client.get(f"/tasks/{task['id']}/evidence").json()
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "user_confirmation"
    assert evidence[0]["note"] == "read it"
    assert evidence[0]["task_id"] == task["id"]
    assert audit_results(client, task["id"]) == [("task.create", "ok"), ("task.complete", "ok")]


def test_stale_version_is_409_and_writes_no_evidence(client: TestClient) -> None:
    task = new_task(client)
    client.patch(f"/tasks/{task['id']}", json={"version": 1, "title": "renamed"})
    stale = client.post(f"/tasks/{task['id']}/complete", json={"version": 1})
    assert stale.status_code == 409
    assert client.get(f"/tasks/{task['id']}").json()["status"] == "todo"
    assert client.get(f"/tasks/{task['id']}/evidence").json() == []
    assert audit_results(client, task["id"])[-1] == ("task.complete", "conflict")


def test_completing_twice_is_409(client: TestClient) -> None:
    task = new_task(client)
    assert client.post(f"/tasks/{task['id']}/complete", json={"version": 1}).status_code == 200
    again = client.post(f"/tasks/{task['id']}/complete", json={"version": 2})
    assert again.status_code == 409
    assert len(client.get(f"/tasks/{task['id']}/evidence").json()) == 1


def test_patch_to_done_is_still_refused(client: TestClient) -> None:
    task = new_task(client)
    refused = client.patch(f"/tasks/{task['id']}", json={"version": 1, "status": "done"})
    assert refused.status_code == 409
    assert client.get(f"/tasks/{task['id']}/evidence").json() == []


def test_unknown_task_and_bad_body(client: TestClient) -> None:
    missing = "01JZZZZZZZZZZZZZZZZZZZZZZZ"
    assert client.post(f"/tasks/{missing}/complete", json={"version": 1}).status_code == 404
    assert client.get(f"/tasks/{missing}/evidence").status_code == 404
    task = new_task(client)
    url = f"/tasks/{task['id']}/complete"
    assert client.post(url, json={"version": 1, "evidence": "trust me"}).status_code == 422
    assert client.post(url, json={"note": "no version"}).status_code == 422


def test_completed_task_keeps_its_evidence_and_cannot_be_deleted(client: TestClient) -> None:
    task = new_task(client)
    client.post(f"/tasks/{task['id']}/complete", json={"version": 1})
    assert client.delete(f"/tasks/{task['id']}").status_code == 409
    assert len(client.get(f"/tasks/{task['id']}/evidence").json()) == 1


def test_hub_serves_the_built_web_ui_without_shadowing_the_api(
    data_dir: Path, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Personal OS</title>", "utf-8")
    with hub_client(Settings(data_dir=data_dir), web_dist=dist) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Personal OS" in page.text
        assert client.get("/tasks").json() == []
        assert client.get("/health").json()["status"] == "ok"


def test_hub_without_a_built_ui_has_no_root_page(data_dir: Path, tmp_path: Path) -> None:
    with hub_client(Settings(data_dir=data_dir), web_dist=tmp_path / "x") as client:
        assert client.get("/").status_code == 404


def test_audit_event_links_to_the_evidence_row(client: TestClient) -> None:
    task = new_task(client)
    client.post(f"/tasks/{task['id']}/complete", json={"version": 1})
    (proof,) = client.get(f"/tasks/{task['id']}/evidence").json()
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        events = audit.list_events(session, "local", task["id"])
    complete = next(e for e in events if e.action == "task.complete")
    assert complete.detail["evidence_id"] == proof["id"]


def test_another_owner_cannot_complete_or_see_the_evidence(data_dir: Path) -> None:
    with hub_client(Settings(data_dir=data_dir)) as mine:
        task = new_task(mine)
    with hub_client(Settings(data_dir=data_dir, owner_id="someone-else")) as theirs:
        assert theirs.post(f"/tasks/{task['id']}/complete", json={"version": 1}).status_code == 404
        assert theirs.get(f"/tasks/{task['id']}/evidence").status_code == 404
    with hub_client(Settings(data_dir=data_dir)) as mine:
        assert mine.get(f"/tasks/{task['id']}").json()["status"] == "todo"
        assert mine.get(f"/tasks/{task['id']}/evidence").json() == []


def test_failure_after_evidence_is_written_rolls_everything_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = new_task(client)
    real_record = audit.record

    def failing_record(session: Session, **kwargs: Any) -> None:
        if kwargs["action"] == "task.complete" and kwargs["result"] == "ok":
            raise RuntimeError("disk full while writing the audit row")
        real_record(session, **kwargs)

    monkeypatch.setattr(audit, "record", failing_record)
    with pytest.raises(RuntimeError, match="disk full"):
        client.post(f"/tasks/{task['id']}/complete", json={"version": 1})
    monkeypatch.undo()

    assert client.get(f"/tasks/{task['id']}").json()["status"] == "todo"
    assert client.get(f"/tasks/{task['id']}/evidence").json() == []


def test_done_task_cannot_be_reopened_but_can_be_renamed(client: TestClient) -> None:
    task = new_task(client)
    client.post(f"/tasks/{task['id']}/complete", json={"version": 1})
    url = f"/tasks/{task['id']}"
    reopened = client.patch(url, json={"version": 2, "status": "todo"})
    assert reopened.status_code == 409
    assert "cannot be reopened" in reopened.json()["detail"]
    renamed = client.patch(url, json={"version": 2, "title": "Read lab 3 handout (done)"})
    assert renamed.status_code == 200
    assert renamed.json()["status"] == "done"


@pytest.mark.parametrize("host", ["testserver", "evil.example", "127.0.0.1.evil.example"])
def test_requests_for_another_host_are_refused(data_dir: Path, host: str) -> None:
    with hub_client(Settings(data_dir=data_dir)) as client:
        response = client.get("/tasks", headers={"Host": host})
        assert response.status_code == 400
        assert client.get("/tasks").status_code == 200


def test_wildcard_bind_address_is_not_an_allowed_host() -> None:
    from apps.hub.main import _allowed_hosts  # pyright: ignore[reportPrivateUsage]

    assert _allowed_hosts("0.0.0.0") == ["127.0.0.1", "localhost"]
    assert _allowed_hosts("my-pc.tailnet.ts.net") == [
        "127.0.0.1",
        "localhost",
        "my-pc.tailnet.ts.net",
    ]
