# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation)
"""Course profiles (ADR 0040) and the grade engine following them."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.hub.core.settings import Settings
from packages.contracts.academic import GradeBand, letter_for
from tests.hub.support import hub_client
from tests.hub.test_gpa import canvas, item

NOW = datetime.now(UTC)

CIS_SCALE = [
    {"letter": "A+", "min": 98},
    {"letter": "A", "min": 92},
    {"letter": "A-", "min": 90},
    {"letter": "B+", "min": 88},
    {"letter": "B", "min": 82},
    {"letter": "F", "min": 0},
]


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        yield client, client.app.state.engine  # type: ignore[attr-defined]


def fields(code: str = "CIS D022A", **over: Any) -> dict[str, Any]:
    return {
        "code": code,
        "title": "C++",
        "units": 4.5,
        "scale": CIS_SCALE,
        "categories": [
            {"name": "zyBooks 作业", "weight": 30, "match": "ZB#"},
            {"name": "zyBooks 实验", "weight": 20, "match": "ZB# Lab"},
            {"name": "期中", "weight": 25, "match": "Midterm"},
            {"name": "期末", "weight": 25, "match": "Final"},
        ],
        "rules": [{"kind": "late", "text": "不收迟交", "source": "No late work"}],
        "open_questions": ["ZB30 算哪类？"],
        **over,
    }


def put(client: TestClient, version: int | None = None, **over: Any) -> dict[str, Any]:
    f = fields(**over)
    r = client.put(f"/academic/profiles/{f['code']}", json={"fields": f, "version": version})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_confirm_and_a_change_clears_the_confirmation(hub) -> None:
    client, _ = hub
    p = put(client)
    assert p["version"] == 1 and p["confirmed_at"] is None
    c = client.post("/academic/profiles/CIS D022A/confirm", json={"version": 1})
    assert c.status_code == 200 and c.json()["confirmed_at"]
    same = put(client, version=c.json()["version"])
    assert same["confirmed_at"] is not None  # nothing changed: still confirmed
    changed = put(client, version=same["version"], units=4.0)
    assert changed["confirmed_at"] is None and changed["units"] == 4.0
    assert [x["code"] for x in client.get("/academic/profiles").json()] == ["CIS D022A"]


def test_stale_versions_and_unknown_codes(hub) -> None:
    client, _ = hub
    put(client)
    stale = client.put("/academic/profiles/CIS D022A", json={"fields": fields(), "version": None})
    assert stale.status_code == 409
    assert client.post("/academic/profiles/X 1/confirm", json={"version": 1}).status_code == 404
    assert client.get("/academic/profiles/X 1").status_code == 404
    bad = client.put("/academic/profiles/OTHER 1", json={"fields": fields(), "version": None})
    assert bad.status_code == 422  # path and body name different courses


@pytest.mark.parametrize(
    "over",
    [
        {"categories": [{"name": "a", "weight": 50}]},  # weights do not add up to 100
        {"scale": [{"letter": "B", "min": 80}, {"letter": "A", "min": 90}]},  # not descending
        {"scale": [{"letter": "C-", "min": 60}]},  # De Anza gives no C-
        {"categories": [{"name": "a", "weight": 100, "match": "ZB**"}]},  # doubled wildcard
        {"scale": [{"letter": "A", "min": 90}, {"letter": "B", "min": 80}]},  # does not reach 0
        {"rules": [{"kind": "rumour", "text": "x"}]},
    ],
)
def test_bad_profiles_are_refused(hub, over: dict[str, Any]) -> None:
    client, _ = hub
    r = client.put("/academic/profiles/CIS D022A", json={"fields": fields(**over), "version": None})
    assert r.status_code == 422


def test_letter_for_uses_the_scale() -> None:
    scale = [GradeBand(letter=b["letter"], min=b["min"]) for b in CIS_SCALE]
    assert letter_for(scale, 92) == "A" and letter_for(scale, 91.99) == "A-"
    assert letter_for(scale, 0) == "F" and letter_for([], 50) is None


def seed_cis(engine: Engine) -> None:
    """CIS as Canvas has it: one unweighted group, so Canvas's score is points-based."""
    iid = canvas(engine)
    code = "F26 CIS D022A 54Y Beg Prog Method C++"
    item(
        engine,
        iid,
        "canvas_course",
        "c1",
        code,
        course_code=code,
        current_score=80.0,
        current_grade="A",  # Canvas's letter, on Canvas's own scale
        weighted=False,
        groups=[{"id": 1, "name": "Assignments", "weight": 0.0}],
    )
    past = NOW - timedelta(days=3)
    graded: list[tuple[str, float, float]] = [
        ("ZB01", 2, 2),
        ("ZB02", 2, 2),  # zyBooks: 4/4 = 100%
        ("ZB01 Lab", 2, 1),  # labs: 1/2 = 50%
        ("Midterm", 25, 22.5),  # 90%
    ]
    for n, (title, pts, score) in enumerate(graded):
        item(
            engine,
            iid,
            "canvas_assignment",
            f"a{n}",
            title,
            past,
            course_code=code,
            group_id=1,
            points_possible=pts,
            score=score,
            submission_state="graded",
        )
    item(
        engine,
        iid,
        "canvas_assignment",
        "f",
        "Final",
        NOW + timedelta(days=20),
        course_code=code,
        group_id=1,
        points_possible=25,
        score=None,
        submission_state="unsubmitted",
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "x",
        "Bonus survey",
        past,
        course_code=code,
        group_id=1,
        points_possible=1,
        score=1,
        submission_state="graded",
    )


def test_the_syllabus_weights_and_scale_decide_the_letter(hub) -> None:
    client, engine = hub
    seed_cis(engine)
    put(client)
    course = client.get("/gpa").json()["courses"][0]
    # (30*100 + 20*50 + 25*90) / 75 = 83.33; the final (25) is still open
    assert course["basis"] == "syllabus" and course["percent"] == pytest.approx(83.33, abs=0.01)
    assert course["letter"] == "B" and course["letter_source"] == "syllabus"
    assert course["grade_points"] == 3.0 and course["units"] == 4.5
    notes = " ".join(course["notes"])
    assert "Canvas 显示 A，按大纲的分数线是 B" in notes
    assert "按大纲的类别和权重算是 83.33%" in notes
    assert "Bonus survey" in notes  # not in any syllabus category: said, not silently counted
    assert "待确认：ZB30 算哪类？" in notes
    lines = {line["label"]: line for line in course["lines"]}
    assert list(lines) == ["A-（90%）", "B+（88%）", "B（82%）"]  # around the current B
    # A- needs (90*100 - 83.33*75) / 25 = 110: out of reach; B needs 78: reachable
    assert lines["A-（90%）"]["status"] == "out_of_reach"
    assert lines["B（82%）"]["status"] == "reachable"


def test_without_a_profile_canvas_is_used_as_before(hub) -> None:
    client, engine = hub
    seed_cis(engine)
    course = client.get("/gpa").json()["courses"][0]
    assert course["basis"] == "canvas" and course["percent"] == 80.0
    assert course["letter"] == "A" and course["letter_source"] == "canvas"
    assert course["profile_confirmed"] is None and course["units"] is None
    assert client.get("/gpa").json()["gpa_weighted"] is False


def test_gpa_is_weighted_by_units_with_de_anza_points(hub) -> None:
    client, engine = hub
    seed_cis(engine)
    iid = canvas(engine)
    code = "F26 MATH D001A 49 Calculus I"
    item(
        engine,
        iid,
        "canvas_course",
        "m1",
        code,
        course_code=code,
        current_score=96.0,
        current_grade="A",
        weighted=True,
        groups=[],
    )
    put(client)  # CIS: B (3.0), 4.5 units
    math_scale = [
        {"letter": "A+", "min": 97},
        {"letter": "A", "min": 90},
        {"letter": "F", "min": 0},
    ]
    put(client, code="MATH D001A", units=5, scale=math_scale, categories=[], open_questions=[])
    view = client.get("/gpa").json()
    assert view["gpa_weighted"] is True and view["units_total"] == 9.5
    assert view["gpa"] == round((3.0 * 4.5 + 4.0 * 5) / 9.5, 2)  # A (96 < 97): 4.0


def test_a_missing_copy_of_handed_in_work_is_not_counted_as_zero(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    code = "F26 ENGL C1000 35Y Academic Reading And Writing"
    item(
        engine,
        iid,
        "canvas_course",
        "e1",
        code,
        course_code=code,
        current_score=90.0,
        current_grade="A-",
        weighted=False,
        groups=[{"id": 1, "name": "EWRT1A"}, {"id": 2, "name": "Imported"}],
    )
    past = NOW - timedelta(days=30)
    item(
        engine,
        iid,
        "canvas_assignment",
        "e2",
        " Introduce Yourself ",
        past,
        course_code=code,
        group_id=1,
        points_possible=2,
        score=2,
        submission_state="graded",
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "e3",
        "Introduce  yourself",
        past,
        course_code=code,
        group_id=2,
        points_possible=2,
        score=None,
        missing=True,
        submission_state="unsubmitted",
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "e4",
        "Journal #9",
        past,
        course_code=code,
        group_id=1,
        points_possible=2,
        score=None,
        missing=True,
        submission_state="unsubmitted",
    )
    course = client.get("/gpa").json()["courses"][0]
    assert [w["title"] for w in course["missing"]] == ["Journal #9"]  # the copy is not missing
    assert any("同名" in n and "Introduce  yourself" in n for n in course["notes"])
    assert course["percent"] == 45.0  # Canvas 90% on the graded half, the real missing half as 0
    assert any("没把 1 份缺交算成 0" in n for n in course["notes"])


def test_title_patterns_are_whole_title_wildcards() -> None:
    from packages.contracts.academic import title_pattern

    p = title_pattern("ZB# Lab")
    assert p.fullmatch("ZB01 Lab") and p.fullmatch("zb7 lab")
    assert not p.fullmatch("ZB01") and not p.fullmatch("ZB01 Lab extra")
    assert title_pattern("(a+)+$").fullmatch("(a+)+$")  # taken literally, never as a regex
    assert title_pattern("Exam*").fullmatch("Exam 2 - Chrome only")


def test_codes_are_normalised(hub) -> None:
    client, _ = hub
    f = fields(code="cis  d022a")
    r = client.put("/academic/profiles/CIS D022A", json={"fields": f, "version": None})
    assert r.status_code == 200 and r.json()["code"] == "CIS D022A"


def test_a_half_graded_category_counts_at_its_average_times_weight(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    code = "F26 CIS D022A 54Y Beg Prog Method C++"
    item(
        engine,
        iid,
        "canvas_course",
        "h1",
        code,
        course_code=code,
        current_score=None,
        current_grade="",
        weighted=False,
        groups=[{"id": 1, "name": "Assignments"}],
    )
    past, later = NOW - timedelta(days=2), NOW + timedelta(days=9)
    for n in range(10):  # zyBooks: all ten graded at 100%
        item(
            engine,
            iid,
            "canvas_assignment",
            f"z{n}",
            f"ZB{n:02d}",
            past,
            course_code=code,
            group_id=1,
            points_possible=2,
            score=2,
            submission_state="graded",
        )
    item(
        engine,
        iid,
        "canvas_assignment",
        "l0",
        "ZB00 Lab",
        past,
        course_code=code,
        group_id=1,
        points_possible=2,
        score=0,
        submission_state="graded",
    )
    for n in range(1, 10):  # labs: one of ten graded, at 0%
        item(
            engine,
            iid,
            "canvas_assignment",
            f"l{n}",
            f"ZB{n:02d} Lab",
            later,
            course_code=code,
            group_id=1,
            points_possible=2,
            score=None,
            submission_state="unsubmitted",
        )
    put(
        client,
        categories=[
            {"name": "zyBooks 作业", "weight": 60, "match": "ZB#"},
            {"name": "zyBooks 实验", "weight": 40, "match": "ZB# Lab"},
        ],
        open_questions=[],
    )
    course = client.get("/gpa").json()["courses"][0]
    # each category's average times its weight: (60*100 + 40*0) / 100 = 60
    assert course["percent"] == 60.0


def test_a_copy_note_survives_own_categories_and_weekly_titles_stay_missing(hub) -> None:
    client, engine = hub
    seed_cis(engine)
    iid = canvas(engine)
    code = "F26 CIS D022A 54Y Beg Prog Method C++"
    past = NOW - timedelta(days=3)
    # a copy: same title and points as the graded ZB01, imported into another group
    item(
        engine,
        iid,
        "canvas_assignment",
        "dup",
        "ZB01",
        past,
        course_code=code,
        group_id=2,
        points_possible=2,
        score=None,
        missing=True,
        submission_state="unsubmitted",
    )
    # a weekly title: same group and points as ZB02, another due date: really missing
    item(
        engine,
        iid,
        "canvas_assignment",
        "wk",
        "ZB02",
        past - timedelta(days=7),
        course_code=code,
        group_id=1,
        points_possible=2,
        score=None,
        missing=True,
        submission_state="unsubmitted",
    )
    put(client)
    course = client.get("/gpa").json()["courses"][0]
    assert any("同名" in n and "ZB01" in n for n in course["notes"])
    assert [w["title"] for w in course["missing"]] == ["ZB02"]
