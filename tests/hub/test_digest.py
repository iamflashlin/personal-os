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
        {"channel": "news", "source_name": "x", "title": "   "},  # whitespace only
        {
            "channel": "news",
            "source_name": "x",
            "title": "t",
            "published_at": "2026-11-12T08:00:00",
        },
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


def test_read_all_respects_the_channel_filter(client) -> None:
    add(client, title="时事 1", channel="news", source_name="Reuters")
    add(client, title="社团 1", channel="club", source_name="CS Club")
    r = client.post("/digest/read-all", params={"view": "today", "channel": "news", **TZ})
    assert r.json() == {"marked": 1}
    unread = [i["title"] for i in view(client, unread_only=True)["items"]]
    assert "社团 1" in unread and "时事 1" not in unread
    assert client.post("/digest/read-all", params={"view": "history", **TZ}).json() == {"marked": 0}


def test_same_title_on_another_day_is_a_new_item(client) -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    add(client, title="本周活动", channel="club", source_name="CS Club", published_at=yesterday)
    add(client, title="本周活动", channel="club", source_name="CS Club")  # today: accepted
    same_day = client.post(
        "/digest/items", json={"channel": "club", "source_name": "CS Club", "title": "本周活动"}
    )
    assert same_day.status_code == 409


def test_a_future_publish_time_is_clamped_to_now(client) -> None:
    later = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    item = add(client, title="未来", published_at=later)
    assert datetime.fromisoformat(item["published_at"]) <= datetime.now(UTC)


def test_the_local_midnight_boundary_and_owner_scoping(tmp_path) -> None:
    from zoneinfo import ZoneInfo

    from sqlalchemy.orm import Session

    from apps.hub.core.db import make_engine, upgrade_to_head
    from apps.hub.core.domain import Actor
    from apps.hub.digest import service
    from packages.contracts.digest import NewDigestItem

    engine = make_engine(tmp_path)
    upgrade_to_head(engine)
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 11, 12, 10, 0, tzinfo=la)  # 18:00 UTC
    midnight = datetime(2026, 11, 12, 0, 0, tzinfo=la)
    me, other = Actor(owner_id="local", source="t"), Actor(owner_id="other", source="t")
    with Session(engine) as s:
        for title, at in (
            ("before", midnight - timedelta(minutes=1)),
            ("after", midnight + timedelta(minutes=1)),
        ):
            service.add(
                s,
                me,
                NewDigestItem(
                    channel="news", source_name="R", title=title, raw_text="原文", published_at=at
                ),
                now,
            )
        service.add(s, other, NewDigestItem(channel="news", source_name="R", title="theirs"), now)
        today = service.view(s, me, "today", now, la)
        history = service.view(s, me, "history", now, la)
        assert [i.title for i in today.items] == ["after"]
        assert [i.title for i in history.items] == ["before"]  # 23:59 local is yesterday
        assert today.items[0].raw_text == "原文"  # kept when read back
        item_id = today.items[0].id
        with pytest.raises(Exception, match="没有这条简报"):
            service.set_read(s, other, item_id, True, now)
        assert [i.title for i in service.view(s, other, "today", now, la).items] == ["theirs"]
