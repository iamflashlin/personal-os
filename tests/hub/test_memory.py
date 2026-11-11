# ruff: noqa: RUF001  (Chinese test sentences use full-width punctuation on purpose)
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.backup.service import export_data, import_data
from apps.hub.core.db import DB_FILENAME
from apps.hub.core.settings import Settings
from tests.hub.support import hub_client

MISSING = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def remember(client: TestClient, body: str, **fields: Any) -> dict[str, Any]:
    response = client.post("/memories", json={"kind": "fact", "body": body, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def search(client: TestClient, q: str, **params: Any) -> list[str]:
    response = client.get("/memories/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return [hit["memory"]["body"] for hit in response.json()]


def audit_details(client: TestClient, memory_id: str) -> list[dict[str, Any]]:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        return [e.detail for e in audit.list_events(session, "local", memory_id)]


def test_create_get_list_update_delete(client: TestClient) -> None:
    created = remember(client, "我喜欢早上学习 C++", kind="preference", source_ref="chat")
    assert created["provenance"] == "raw"
    assert created["confidence"] == 1.0
    assert created["sensitivity"] == "normal"
    url = f"/memories/{created['id']}"
    assert client.get(url).json() == created
    assert [m["id"] for m in client.get("/memories").json()] == [created["id"]]

    fixed = client.patch(url, json={"version": 1, "body": "我喜欢晚上学习 C++"})
    assert fixed.status_code == 200
    assert fixed.json()["version"] == 2
    assert fixed.json()["kind"] == "preference"

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_errors_404_422_409(client: TestClient) -> None:
    assert client.get(f"/memories/{MISSING}").status_code == 404
    assert client.patch(f"/memories/{MISSING}", json={"version": 1}).status_code == 404
    assert client.post("/memories", json={"kind": "fact"}).status_code == 422
    assert client.post("/memories", json={"kind": "mood", "body": "x"}).status_code == 422
    assert (
        client.post("/memories", json={"kind": "fact", "body": "x", "confidence": 2}).status_code
        == 422
    )
    memory = remember(client, "a")
    url = f"/memories/{memory['id']}"
    assert client.patch(url, json={"version": 1, "body": "b"}).status_code == 200
    assert client.patch(url, json={"version": 1, "body": "c"}).status_code == 409


def test_every_write_is_audited_once(client: TestClient) -> None:
    memory = remember(client, "CIS lab is on Fridays")
    url = f"/memories/{memory['id']}"
    client.patch(url, json={"version": 1, "body": "CIS lab is on Thursdays"})
    client.post(f"{url}/confirm", json={"version": 2})
    client.patch(url, json={"version": 1, "body": "stale"})
    client.delete(url)
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        events = audit.list_events(session, "local", memory["id"])
    assert [(e.action, e.result) for e in events] == [
        ("memory.create", "ok"),
        ("memory.update", "ok"),
        ("memory.confirm", "ok"),
        ("memory.update", "conflict"),
        ("memory.delete", "ok"),
    ]


@pytest.mark.parametrize("sensitivity", ["private", "secret"])
def test_sensitive_bodies_never_reach_the_audit_log(client: TestClient, sensitivity: str) -> None:
    memory = remember(client, "银行卡后四位 4821", sensitivity=sensitivity)
    client.patch(f"/memories/{memory['id']}", json={"version": 1, "body": "银行卡后四位 9930"})
    stored = str(audit_details(client, memory["id"]))
    assert "4821" not in stored and "9930" not in stored
    assert "sha256" in stored


def test_making_a_memory_sensitive_hides_the_new_body_too(client: TestClient) -> None:
    memory = remember(client, "ordinary note")
    client.patch(
        f"/memories/{memory['id']}",
        json={"version": 1, "body": "now private: 4821", "sensitivity": "private"},
    )
    assert "4821" not in str(audit_details(client, memory["id"]))


def test_verified_provenance_is_reserved_and_confirm_sets_user_confirmed(
    client: TestClient,
) -> None:
    refused = client.post("/memories", json={"kind": "fact", "body": "x", "provenance": "verified"})
    assert refused.status_code == 422
    guess = remember(client, "user prefers dark mode", provenance="ai_inferred", confidence=0.4)
    url = f"/memories/{guess['id']}"
    assert client.patch(url, json={"version": 1, "provenance": "verified"}).status_code == 422
    confirmed = client.post(f"{url}/confirm", json={"version": 1})
    assert confirmed.status_code == 200
    assert confirmed.json()["provenance"] == "user_confirmed"
    assert confirmed.json()["confidence"] == 1.0


def test_naive_expiry_is_refused(client: TestClient) -> None:
    naive = client.post(
        "/memories", json={"kind": "fact", "body": "x", "expires_at": "2030-01-01T00:00:00"}
    )
    assert naive.status_code == 422


def test_search_finds_chinese_and_english_substrings(client: TestClient) -> None:
    remember(client, "我喜欢早上学习 C++，晚上复习英语")
    remember(client, "CIS lab 3 is due on Friday")
    remember(client, "Prefers dark mode in VS Code")

    assert search(client, "早上学习") == ["我喜欢早上学习 C++，晚上复习英语"]
    assert search(client, "学习") == ["我喜欢早上学习 C++，晚上复习英语"]
    assert search(client, "英语") == ["我喜欢早上学习 C++，晚上复习英语"]
    assert search(client, "dark") == ["Prefers dark mode in VS Code"]
    assert search(client, "DARK MODE") == ["Prefers dark mode in VS Code"]
    assert search(client, "lab Friday") == ["CIS lab 3 is due on Friday"]
    assert search(client, "lab 英语") == []
    assert search(client, "不存在的内容") == []


def test_search_ranks_fts_hits_and_treats_operators_as_text(client: TestClient) -> None:
    remember(client, 'quote "OR" NOT and 100% done_rate')
    assert search(client, '"OR"') == ['quote "OR" NOT and 100% done_rate']
    assert search(client, "100%") == ['quote "OR" NOT and 100% done_rate']
    assert search(client, "e_r") == ['quote "OR" NOT and 100% done_rate']
    assert search(client, "x_y") == []
    hits = client.get("/memories/search", params={"q": "quote"}).json()
    assert isinstance(hits[0]["rank"], float)
    assert client.get("/memories/search", params={"q": " "}).status_code == 422


def test_search_follows_edits_and_deletes(client: TestClient) -> None:
    memory = remember(client, "meeting with advisor on Monday")
    url = f"/memories/{memory['id']}"
    client.patch(url, json={"version": 1, "body": "meeting with advisor on Wednesday"})
    assert search(client, "Monday") == []
    assert search(client, "Wednesday") == ["meeting with advisor on Wednesday"]
    client.delete(url)
    assert search(client, "Wednesday") == []


def test_expired_and_secret_memories_are_hidden_unless_asked(client: TestClient) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    remember(client, "old exam room B101", expires_at=past)
    remember(client, "new exam room C202", expires_at=future)
    remember(client, "exam password 2468", sensitivity="secret")

    assert search(client, "exam") == ["new exam room C202"]
    assert sorted(search(client, "exam", include_expired=True, include_secret=True)) == [
        "exam password 2468",
        "new exam room C202",
        "old exam room B101",
    ]
    listed = [m["body"] for m in client.get("/memories").json()]
    assert "old exam room B101" not in listed
    assert "old exam room B101" in [
        m["body"] for m in client.get("/memories", params={"include_expired": True}).json()
    ]


def test_another_owner_sees_nothing(data_dir: Path) -> None:
    with hub_client(Settings(data_dir=data_dir)) as mine:
        memory = remember(mine, "my private plan for the weekend")
    with hub_client(Settings(data_dir=data_dir, owner_id="someone-else")) as theirs:
        assert theirs.get(f"/memories/{memory['id']}").status_code == 404
        assert theirs.get("/memories").json() == []
        assert theirs.get("/memories/search", params={"q": "weekend"}).json() == []


def test_export_import_keeps_memories_searchable(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    remember(client, "我想在暑假前学完数据结构")
    remember(client, "Likes long walks after dinner")
    package = tmp_path / "export.zip"
    export_data(data_dir, package)
    restored = tmp_path / "restored"
    import_data(package, restored)
    with hub_client(Settings(data_dir=restored)) as again:
        assert search(again, "数据结构") == ["我想在暑假前学完数据结构"]
        assert search(again, "walks") == ["Likes long walks after dinner"]
        added = remember(again, "new memory after restore")
        assert search(again, "after restore") == [added["body"]]


def test_search_does_not_depend_on_sqlite_rowids(client: TestClient, data_dir: Path) -> None:
    """VACUUM may renumber rowids of a table without an INTEGER PRIMARY KEY, and an Alembic
    batch migration rebuilds the table by copying it. Either moves every rowid."""
    remember(client, "bravo note about lab")
    remember(client, "charlie note about exams")
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        conn.execute("UPDATE memory SET rowid = rowid + 100")
        conn.commit()
    assert search(client, "lab") == ["bravo note about lab"]
    assert search(client, "exams") == ["charlie note about exams"]


def test_short_terms_escape_like_wildcards(client: TestClient) -> None:
    remember(client, "progress is 100% today")
    remember(client, "file_name_v2 saved")
    assert search(client, "0%") == ["progress is 100% today"]
    assert search(client, "x%") == []
    assert search(client, "e_") == ["file_name_v2 saved"]
    assert search(client, "%") == ["progress is 100% today"]


def test_and_across_short_and_long_terms(client: TestClient) -> None:
    remember(client, "我喜欢早上学习 C++，晚上复习英语")
    remember(client, "Prefers dark mode")
    assert search(client, "C++ 英语") == ["我喜欢早上学习 C++，晚上复习英语"]
    assert search(client, "学习 英语") == ["我喜欢早上学习 C++，晚上复习英语"]
    assert search(client, "学习 dark") == []


def test_short_term_search_still_hides_expired_and_secret(client: TestClient) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    remember(client, "考试 room B101", expires_at=past)
    remember(client, "考试 password 2468", sensitivity="secret")
    remember(client, "考试 week plan")
    assert search(client, "考试") == ["考试 week plan"]


def test_fts_triggers_exist_at_head(client: TestClient, data_dir: Path) -> None:
    """A batch migration that rebuilds `memory` drops these; the index then goes stale."""
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'memory'"
            )
        }
    assert names == {"memory_fts_ai", "memory_fts_ad", "memory_fts_au"}


def test_sqlite_build_supports_fts5_trigram() -> None:
    """One clear failure if a platform's SQLite lacks what migration 0004 needs."""
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        conn.execute("INSERT INTO t(x) VALUES ('我喜欢早上学习')")
        hits = conn.execute("SELECT x FROM t WHERE t MATCH '\"早上学\"'").fetchall()
    assert hits == [("我喜欢早上学习",)], f"SQLite {sqlite3.sqlite_version}"
