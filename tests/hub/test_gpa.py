from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.core.settings import Settings
from apps.hub.gpa.service import _line, course_code
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow
from tests.hub.support import hub_client

NOW = datetime.now(UTC)


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        yield client, client.app.state.engine  # type: ignore[attr-defined]


def canvas(engine: Engine) -> str:
    with Session(engine) as s:
        row = IntegrationRow(
            owner_id="local",
            source="test",
            version=1,
            kind="canvas",
            name="Canvas",
            credential_name="x",
            interval_s=900,
            config={},
            status="ok",
            last_error="",
            cursor={},
        )
        s.add(row)
        s.commit()
        return row.id


def item(
    engine: Engine,
    iid: str,
    item_type: str,
    ext: str,
    title: str,
    at: datetime | None = None,
    **data: Any,
) -> str:
    with Session(engine) as s:
        row = SyncedItemRow(
            owner_id="local",
            source="test",
            version=1,
            integration_id=iid,
            item_type=item_type,
            external_id=ext,
            content_hash=ext,
            title=title,
            body="",
            location="",
            url=f"https://c/{ext}",
            starts_at=at,
            ends_at=None,
            all_day=False,
            data=data,
        )
        s.add(row)
        s.commit()
        return row.id


def seed(engine: Engine) -> None:
    iid = canvas(engine)
    item(
        engine,
        iid,
        "canvas_course",
        "1",
        "F26 MATH D001A 49 Calculus I",
        course_code="F26 MATH D001A 49 Calculus I",
        current_score=95.0,
        current_grade="A",
        final_score=40.0,
        weighted=True,
        groups=[
            {"id": 10, "name": "Homework", "weight": 40.0},
            {"id": 11, "name": "Final", "weight": 60.0},
        ],
    )
    item(
        engine,
        iid,
        "canvas_course",
        "2",
        "DA ISP New Student Orientation",
        course_code="DA ISP New Student Orientation",
        current_score=None,
        weighted=False,
        groups=[],
    )
    code = "F26 MATH D001A 49 Calculus I"
    item(
        engine,
        iid,
        "canvas_assignment",
        "1:1",
        "HW 1",
        NOW - timedelta(days=5),
        course_code=code,
        group_id=10,
        points_possible=10,
        score=9.5,
        submission_state="graded",
        graded_at=(NOW - timedelta(days=1)).isoformat(),
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "1:2",
        "HW 2",
        NOW - timedelta(days=2),
        course_code=code,
        group_id=10,
        points_possible=10,
        score=None,
        missing=True,
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "1:3",
        "HW 3",
        NOW + timedelta(days=3),
        course_code=code,
        group_id=10,
        points_possible=10,
        score=None,
        submission_state="unsubmitted",
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "1:4",
        "HW excused",
        NOW - timedelta(days=9),
        course_code=code,
        group_id=10,
        points_possible=10,
        excused=True,
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "1:5",
        "Final",
        NOW + timedelta(days=30),
        course_code=code,
        group_id=11,
        points_possible=100,
        score=None,
    )
    item(
        engine,
        iid,
        "canvas_material",
        "1:501",
        "Syllabus.pdf",
        course_code=code,
        module="Start",
        module_position=1,
        kind="File",
        position=1,
    )


def test_the_gpa_view_summarises_each_credit_course(hub) -> None:
    client, engine = hub
    seed(engine)
    r = client.get("/gpa")
    assert r.status_code == 200, r.text
    v = r.json()
    assert [c["code"] for c in v["courses"]] == ["MATH D001A"]  # orientation left out
    c = v["courses"][0]
    assert c["current_score"] == 95.0 and c["current_grade"] == "A" and c["grade_points"] == 4.0
    hw = next(g for g in c["groups"] if g["name"] == "Homework")
    assert hw == {
        "name": "Homework",
        "weight": 40.0,
        "earned": 9.5,
        "possible": 10.0,
        "percent": 95.0,
        "graded": 1,
        "total": 3,
    }  # excused left out
    assert c["completion"] == {"due_so_far": 2, "done": 1, "missing": 1, "late": 0}
    assert [m["title"] for m in c["missing"]] == ["HW 2"]
    assert [u["title"] for u in c["upcoming"]] == ["HW 3"]
    assert [x["title"] for x in c["recent"]] == ["HW 1"]
    assert [m["title"] for m in c["materials"]] == ["Syllabus.pdf"]
    # Homework (40%): 10 graded, 10 missing (counts 0), 10 open of 30 points; Final (60%) open.
    # graded 13.33 (at Canvas's 95% = 12.67), missing 13.33, open 13.33 + 60 = 73.33
    lines = {line["target"]: line for line in c["lines"]}
    assert lines[90.0]["needed"] == 105.5 and lines[90.0]["status"] == "out_of_reach"
    assert lines[80.0]["needed"] == 91.8 and lines[80.0]["status"] == "reachable"
    assert v["gpa"] == 4.0 and "估算" in v["gpa_note"]


def test_grade_lines() -> None:
    # 40% of the course graded at 95%, 60% left: 90% needs (0.9*100 - 38) / 60 = 86.7%
    line = _line("A", 90.0, 38.0, 40.0, 60.0)
    assert line.needed == 86.7 and line.status == "reachable"
    assert _line("A", 90.0, 38.0, 40.0, 0.0).status == "done"
    assert _line("A", 90.0, 30.0, 40.0, 0.0).status == "out_of_reach"
    assert _line("C", 30.0, 38.0, 40.0, 60.0).status == "safe"
    assert _line("A", 99.0, 10.0, 40.0, 10.0).status == "out_of_reach"


def test_course_codes() -> None:
    assert course_code("F26 CIS D022A 54Y Beg Prog Method C++") == "CIS D022A"
    assert course_code("F26 ECON C2002 03Y Prin Macroeconomics") == "ECON C2002"
    assert course_code("DA ISP New Student Orientation") == ""
    assert course_code("Physical Sciences and Technology") == ""


def test_points_course_states_and_lines(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    code = "F26 ENGL C1000 35Y Academic Reading"
    item(
        engine,
        iid,
        "canvas_course",
        "9",
        code,
        course_code=code,
        current_score=80.0,
        current_grade="B-",
        weighted=False,
        groups=[{"id": 1, "name": "All", "weight": 0}],
    )
    past, soon = NOW - timedelta(days=3), NOW + timedelta(days=2)
    rows = [
        ("graded", past, {"score": 8.0, "points_possible": 10, "submission_state": "graded"}),
        (
            "late",
            past,
            {"score": 8.0, "points_possible": 10, "submission_state": "graded", "late": True},
        ),
        ("flagged", past, {"points_possible": 10, "missing": True}),
        ("in class", past, {"points_possible": 10, "submission_state": "unsubmitted"}),
        ("handed in", past, {"points_possible": 10, "submission_state": "submitted"}),
        ("excused", past, {"points_possible": 10, "excused": True}),
        ("omitted", past, {"points_possible": 10, "omit_from_final": True, "score": 0.0}),
        ("next", soon, {"points_possible": 20}),
    ]
    for i, (title, at, extra) in enumerate(rows):
        item(
            engine,
            iid,
            "canvas_assignment",
            f"9:{i}",
            title,
            at,
            course_code=code,
            group_id=1,
            **extra,
        )
    c = next(x for x in client.get("/gpa").json()["courses"] if x["code"] == "ENGL C1000")
    states = {w["title"]: w["state"] for w in [*c["missing"], *c["upcoming"]]}
    assert states == {"flagged": "missing", "next": "upcoming"}  # only Canvas's flag is missing
    # in class: awaiting a grade, neither done nor missing; excused and omitted are left out
    assert c["completion"] == {"due_so_far": 4, "done": 3, "missing": 1, "late": 1}
    # counted points: graded 20 (Canvas 80% -> 16), missing 10, open: in class 10 + handed in
    # 10 + next 20 = 40, total 70. B line (80%): (56 - 16) / 40 = 100% exactly.
    lines = {line["target"]: line for line in c["lines"]}
    assert lines[80.0]["needed"] == 100.0 and lines[80.0]["status"] == "reachable"
    assert lines[70.0]["needed"] == 82.5


def test_no_graded_or_open_work_means_no_lines(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    code = "F26 CIS D022A 54Y"
    item(
        engine,
        iid,
        "canvas_course",
        "7",
        code,
        course_code=code,
        current_score=None,
        current_grade="",
        weighted=True,
        groups=None,
    )
    c = next(x for x in client.get("/gpa").json()["courses"] if x["code"] == "CIS D022A")
    assert c["lines"] == [] and c["groups"] == [] and c["grade_points"] is None
