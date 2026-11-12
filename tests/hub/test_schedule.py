# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.core.settings import Settings
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from tests.hub.support import hub_client

LA = ZoneInfo("America/Los_Angeles")
TZ = {"time_zone": "America/Los_Angeles"}


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        yield client, client.app.state.engine  # type: ignore[attr-defined]


def local(y: int, mo: int, d: int, h: int, mi: int = 0) -> str:
    return datetime(y, mo, d, h, mi, tzinfo=LA).isoformat()


def event(client: TestClient, **over: Any) -> dict[str, Any]:
    body = {
        "title": "CIS 22A 上课",
        "kind": "class",
        "starts_at": local(2026, 11, 9, 10),
        "ends_at": local(2026, 11, 9, 11, 50),
        **over,
    }
    r = client.post("/schedule/events", params=TZ, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def agenda(client: TestClient, start: str, end: str) -> dict[str, Any]:
    r = client.get("/schedule", params={"start": start, "end": end, **TZ})
    assert r.status_code == 200, r.text
    return r.json()


def synced(
    engine: Engine,
    item_type: str,
    title: str,
    at: datetime,
    end: datetime | None = None,
    **data: Any,
) -> None:
    with Session(engine) as s:
        integ = IntegrationRow(
            owner_id="local",
            source="t",
            version=1,
            kind="calendar",
            name="c",
            credential_name="x",
            interval_s=900,
            config={},
            status="ok",
            last_error="",
            cursor={},
        )
        s.add(integ)
        s.flush()
        s.add(
            SyncedItemRow(
                owner_id="local",
                source="t",
                version=1,
                integration_id=integ.id,
                item_type=item_type,
                external_id=title,
                content_hash=title,
                title=title,
                body="",
                location="Room 1",
                url="https://x/1",
                starts_at=at,
                ends_at=end,
                all_day=False,
                data=data,
            )
        )
        s.commit()


def test_weekly_classes_repeat_at_the_same_local_time_across_dst(hub) -> None:
    client, _ = hub
    event(
        client,
        repeat_days=["MO", "WE"],
        repeat_until="2026-11-30",
        starts_at=local(2026, 10, 26, 10),
        ends_at=local(2026, 10, 26, 11, 50),
    )
    # DST ended on 2026-11-01 in Los Angeles: the class stays at 10:00 local
    a = agenda(client, local(2026, 10, 26, 0), local(2026, 11, 9, 0))
    starts = [datetime.fromisoformat(e["starts_at"]).astimezone(LA) for e in a["entries"]]
    assert [s.strftime("%m-%d %a %H:%M") for s in starts] == [
        "10-26 Mon 10:00",
        "10-28 Wed 10:00",
        "11-02 Mon 10:00",
        "11-04 Wed 10:00",
    ]
    assert all(e["source"] == "manual" and e["event_id"] for e in a["entries"])
    later = agenda(client, local(2026, 12, 1, 0), local(2026, 12, 15, 0))
    assert later["entries"] == []  # past repeat_until


def test_calendar_events_and_canvas_deadlines_join_and_conflicts_show(hub) -> None:
    client, engine = hub
    event(
        client,
        title="健身",
        kind="workout",
        starts_at=local(2026, 11, 12, 17),
        ends_at=local(2026, 11, 12, 18, 30),
    )
    synced(
        engine,
        "calendar_event",
        "社团活动",
        datetime(2026, 11, 13, 1, 0, tzinfo=UTC),
        datetime(2026, 11, 13, 2, 0, tzinfo=UTC),
    )  # 17:00-18:00 local: overlaps the workout
    synced(
        engine,
        "canvas_assignment",
        "Lab 5",
        datetime(2026, 11, 13, 7, 59, tzinfo=UTC),
        submission_state="unsubmitted",
        course="CIS 22A",
    )
    synced(
        engine,
        "canvas_assignment",
        "Lab 4",
        datetime(2026, 11, 13, 6, 0, tzinfo=UTC),
        submission_state="submitted",
    )
    a = agenda(client, local(2026, 11, 12, 0), local(2026, 11, 13, 0))
    by = {e["title"]: e for e in a["entries"]}
    assert set(by) == {"健身", "社团活动", "Lab 5"}  # a handed-in lab is no deadline
    assert by["健身"]["conflict"] and by["社团活动"]["conflict"]
    deadline = by["Lab 5"]
    assert (
        deadline["blocks"] is False
        and deadline["conflict"] is False
        and deadline["source"] == "canvas"
    )


def test_free_time_skips_busy_blocks_inside_the_day_window(hub) -> None:
    client, _ = hub
    event(client, starts_at=local(2030, 1, 15, 10), ends_at=local(2030, 1, 15, 12))
    event(
        client, title="短会", starts_at=local(2030, 1, 15, 12, 10), ends_at=local(2030, 1, 15, 13)
    )
    a = agenda(client, local(2030, 1, 15, 0), local(2030, 1, 16, 0))
    slots = [
        (
            datetime.fromisoformat(f["starts_at"]).astimezone(LA).strftime("%H:%M"),
            datetime.fromisoformat(f["ends_at"]).astimezone(LA).strftime("%H:%M"),
        )
        for f in a["free"]
    ]
    assert slots == [("08:00", "10:00"), ("13:00", "22:00")]  # the 10-minute gap is too short
    assert a["day_window"] == [8, 22]


def test_edit_and_delete_with_version_checks(hub) -> None:
    client, _ = hub
    e = event(client)
    fields = {
        "title": "CIS 22A 上课（换教室）",
        "kind": "class",
        "starts_at": e["starts_at"],
        "ends_at": e["ends_at"],
        "location": "ATC 205",
    }
    r = client.put(
        f"/schedule/events/{e['id']}", params=TZ, json={"fields": fields, "version": e["version"]}
    )
    assert r.status_code == 200 and r.json()["location"] == "ATC 205"
    stale = client.put(
        f"/schedule/events/{e['id']}", params=TZ, json={"fields": fields, "version": e["version"]}
    )
    assert stale.status_code == 409
    assert client.delete(f"/schedule/events/{e['id']}").status_code == 204
    assert client.delete(f"/schedule/events/{e['id']}").status_code == 404


@pytest.mark.parametrize(
    "over",
    [
        {"ends_at": local(2026, 11, 9, 9)},  # ends before it starts
        {"starts_at": "2026-11-09T10:00:00"},  # no offset
        {"kind": "party"},
        {"repeat_until": "2026-12-01"},  # until without days
        {"repeat_days": ["XX"]},
        {"title": ""},
    ],
)
def test_bad_events_are_refused(hub, over: dict[str, Any]) -> None:
    client, _ = hub
    body = {
        "title": "x",
        "kind": "class",
        "starts_at": local(2026, 11, 9, 10),
        "ends_at": local(2026, 11, 9, 11),
        **over,
    }
    assert client.post("/schedule/events", params=TZ, json=body).status_code == 422


def test_agenda_range_is_checked(hub) -> None:
    client, _ = hub
    r = client.get(
        "/schedule", params={"start": local(2026, 11, 1, 0), "end": local(2027, 3, 1, 0), **TZ}
    )
    assert r.status_code == 422
    r = client.get(
        "/schedule", params={"start": "2026-11-01T00:00:00", "end": "2026-11-02T00:00:00"}
    )
    assert r.status_code == 422
    assert (
        client.get(
            "/schedule", params={"start": local(2026, 11, 2, 0), "end": local(2026, 11, 1, 0), **TZ}
        ).status_code
        == 422
    )
    assert agenda(client, local(2026, 11, 1, 0), local(2026, 11, 2, 0))["entries"] == []


def test_repeat_until_is_inclusive_and_window_start_overlap_counts(hub) -> None:
    client, _ = hub
    event(
        client,
        repeat_days=["MO"],
        repeat_until="2026-11-30",
        starts_at=local(2026, 11, 2, 10),
        ends_at=local(2026, 11, 2, 11, 50),
    )
    a = agenda(client, local(2026, 11, 30, 0), local(2026, 12, 8, 0))
    assert [e["starts_at"][:10] for e in a["entries"]] == ["2026-11-30"]  # 12-07 is after until
    late = agenda(client, local(2026, 11, 9, 10, 30), local(2026, 11, 9, 23))
    assert len(late["entries"]) == 1  # 10:00-11:50 still runs at 10:30


def test_an_overnight_calendar_event_shows_on_the_next_morning(hub) -> None:
    client, engine = hub
    synced(
        engine,
        "calendar_event",
        "夜间活动",
        datetime(2026, 11, 10, 7, 0, tzinfo=UTC),
        datetime(2026, 11, 10, 17, 0, tzinfo=UTC),
    )  # 23:00 Nov 9 to 09:00 Nov 10 local
    synced(
        engine,
        "calendar_event",
        "前一天上午",
        datetime(2026, 11, 9, 18, 0, tzinfo=UTC),
        datetime(2026, 11, 9, 19, 0, tzinfo=UTC),
    )  # Nov 9 10:00-11:00 local: over before
    a = agenda(client, local(2026, 11, 10, 0), local(2026, 11, 11, 0))
    assert [e["title"] for e in a["entries"]] == ["夜间活动"]


def test_an_edit_without_a_zone_keeps_the_entered_zone(hub) -> None:
    client, engine = hub
    e = event(
        client, repeat_days=["MO"], starts_at=local(2026, 11, 2, 10), ends_at=local(2026, 11, 2, 11)
    )
    fields = {
        "title": "改名",
        "kind": "class",
        "starts_at": e["starts_at"],
        "ends_at": e["ends_at"],
        "repeat_days": ["MO"],
    }
    r = client.put(f"/schedule/events/{e['id']}", json={"fields": fields, "version": e["version"]})
    assert r.status_code == 200
    from apps.hub.schedule.models import ScheduleEventRow

    with Session(engine) as s:
        row = s.get(ScheduleEventRow, e["id"])
        assert row is not None and row.time_zone == "America/Los_Angeles"


def test_repeat_until_before_the_start_is_refused(hub) -> None:
    client, _ = hub
    body = {
        "title": "x",
        "kind": "class",
        "starts_at": local(2026, 11, 9, 10),
        "ends_at": local(2026, 11, 9, 11),
        "repeat_days": ["MO"],
        "repeat_until": "2026-11-01",
    }
    assert client.post("/schedule/events", params=TZ, json=body).status_code == 422


def test_free_time_is_listed_only_from_now_on(hub) -> None:
    client, _ = hub
    past = agenda(client, local(2026, 1, 5, 0), local(2026, 1, 6, 0))
    assert past["free"] == []  # a day that is over has no useful free time


def test_an_evening_class_until_its_own_local_day_is_accepted(hub) -> None:
    client, _ = hub
    # 18:00 local on Nov 9 is Nov 10 in UTC; until Nov 9 (local) is still valid
    r = client.post(
        "/schedule/events",
        params=TZ,
        json={
            "title": "晚课",
            "kind": "class",
            "starts_at": datetime(2026, 11, 9, 18, tzinfo=LA).astimezone(UTC).isoformat(),
            "ends_at": datetime(2026, 11, 9, 20, tzinfo=LA).astimezone(UTC).isoformat(),
            "repeat_days": ["MO"],
            "repeat_until": "2026-11-09",
        },
    )
    assert r.status_code == 201, r.text


def test_weekly_entries_say_they_repeat(hub) -> None:
    client, _ = hub
    event(
        client, repeat_days=["MO"], starts_at=local(2026, 11, 2, 10), ends_at=local(2026, 11, 2, 11)
    )
    event(client, title="一次性", starts_at=local(2026, 11, 3, 10), ends_at=local(2026, 11, 3, 11))
    a = agenda(client, local(2026, 11, 2, 0), local(2026, 11, 9, 0))
    assert {e["title"]: e["repeats"] for e in a["entries"]} == {
        "CIS 22A 上课": True,
        "一次性": False,
    }


def test_free_time_starts_at_now_part_way_through_the_day(tmp_path) -> None:
    from sqlalchemy.orm import Session as S

    from apps.hub.core.db import make_engine, upgrade_to_head
    from apps.hub.core.domain import Actor
    from apps.hub.schedule import service

    engine = make_engine(tmp_path)
    upgrade_to_head(engine)
    day = datetime(2026, 11, 12, 0, tzinfo=LA)
    now = datetime(2026, 11, 12, 14, 30, tzinfo=LA)
    with S(engine) as s:
        a = service.agenda(
            s,
            Actor(owner_id="local", source="t"),
            day,
            day + timedelta(days=1),
            LA,
            "America/Los_Angeles",
            now=now,
        )
    assert [
        (f.starts_at.astimezone(LA).strftime("%H:%M"), f.ends_at.astimezone(LA).strftime("%H:%M"))
        for f in a.free
    ] == [("14:30", "22:00")]
