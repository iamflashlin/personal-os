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
    a_line = next(line for line in c["lines"] if line["target"] == 90.0)
    assert a_line["status"] in ("reachable", "safe") and a_line["needed"] is not None
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
