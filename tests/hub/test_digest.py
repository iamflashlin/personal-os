# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation)
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.hub.core.settings import Settings
from tests.hub.support import hub_client

TZ = {"time_zone": "America/Los_Angeles"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as c:
        yield c


def add(client: TestClient, **over: Any) -> dict[str, Any]:
    body = {
        "channel": "group",
        "source_name": "微信转学群",
        "title": "UC 转学申请经验",
        "summary": "· 先查 ASSIST 课程对应\n· 11/30 截止",
        "raw_text": "原始聊天……",
        **over,
    }
    r = client.post("/digest/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def view(client: TestClient, which: str = "today", **params: Any) -> dict[str, Any]:
    r = client.get("/digest", params={"view": which, **TZ, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_today_and_history_with_unread_counts(client) -> None:
    add(client)
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    add(
        client,
        channel="news",
        source_name="Reuters",
        title="Fed holds rates",
        published_at=old,
        url="https://example.com/fed",
        raw_text="",
    )
    add(client, channel="club", source_name="CS Club IG", title="Hackathon 11/20", important=True)
    today = view(client)
    assert [i["title"] for i in today["items"]] == [
        "Hackathon 11/20",
        "UC 转学申请经验",
    ]  # important first
    assert today["unread_today"] == 2 and today["unread_history"] == 1
    assert today["channels"] == {"group": 1, "club": 1}
    history = view(client, "history")
    assert [i["title"] for i in history["items"]] == ["Fed holds rates"]
    assert history["items"][0]["raw_text"] == "" and history["items"][0]["origin"] == "manual"


def test_read_marks_and_filters(client) -> None:
    a = add(client)
    add(client, title="选课技巧：先抢 waitlist", channel="group")
    r = client.put(f"/digest/items/{a['id']}/read", json={"read": True})
    assert r.status_code == 200 and r.json()["read"] is True
    assert [i["title"] for i in view(client, unread_only=True)["items"]] == [
        "选课技巧：先抢 waitlist"
    ]
    assert view(client)["unread_today"] == 1
    assert client.post("/digest/read-all", params={"view": "today", **TZ}).json() == {"marked": 1}
    assert view(client)["unread_today"] == 0
    client.put(f"/digest/items/{a['id']}/read", json={"read": False})
    assert view(client)["unread_today"] == 1
    assert len(view(client, channel="news")["items"]) == 0


def test_the_same_item_is_kept_once_and_raw_text_stays(client) -> None:
    a = add(client, url="https://example.com/x")
    again = client.post(
        "/digest/items",
        json={
            "channel": "group",
            "source_name": "微信转学群",
            "title": "另一个标题",
            "url": "https://example.com/x",
        },
    )
    assert again.status_code == 409
    assert a["raw_text"] == "原始聊天……"


@pytest.mark.parametrize(
    "body",
    [
        {"channel": "tiktok", "source_name": "x", "title": "t"},
        {"channel": "news", "source_name": "", "title": "t"},
        {"channel": "news", "source_name": "x", "title": ""},
        {"channel": "news", "source_name": "x", "title": "t", "extra": 1},
    ],
)
def test_bad_items_are_refused(client, body: dict[str, Any]) -> None:
    assert client.post("/digest/items", json=body).status_code == 422


def test_unknown_item_and_zone(client) -> None:
    assert (
        client.put("/digest/items/01JZZZZZZZZZZZZZZZZZZZZZZZ/read", json={"read": True}).status_code
        == 404
    )
    assert client.get("/digest", params={"time_zone": "Mars/Base"}).status_code == 422
