# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation)
"""The course knowledge map (ADR 0041): structure, assessment links, mastery, exam maps."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.hub.academic.maps import sections_in
from apps.hub.core.settings import Settings
from tests.hub.support import hub_client
from tests.hub.test_gpa import canvas, item

NOW = datetime.now(UTC)
CODE = "F26 MATH D001A 49 Calculus I"


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine]]:
    with hub_client(Settings(data_dir=tmp_path / "data", jobs_enabled=False)) as client:
        yield client, client.app.state.engine  # type: ignore[attr-defined]


def sec(key: str, parent: str, title: str, page: int, prereq: tuple[str, ...] = ()) -> dict:
    return {
        "key": key,
        "kind": "section",
        "parent": parent,
        "title": title,
        "page": page,
        "prereq": list(prereq),
    }


def course_map(**over: Any) -> dict[str, Any]:
    return {
        "course_code": "MATH D001A",
        "material": "Notes.pdf",
        "concepts": [
            {"key": "ch2", "kind": "chapter", "title": "Limits"},
            sec("2.3", "ch2", "Limit laws", 6),
            {"key": "ch3", "kind": "chapter", "title": "Rules"},
            sec("3.1", "ch3", "Power rule", 23),
            sec("3.3", "ch3", "Trig", 28, ("3.1",)),
            sec("3.4", "ch3", "Chain rule", 31, ("3.1", "3.3")),
            {"key": "3.4-chain", "kind": "concept", "parent": "3.4", "title": "Chain", "page": 31},
            sec("3.5", "ch3", "Implicit", 33, ("3.4-chain",)),
            sec("3.11", "ch3", "Hyperbolic", 47, ("2.3",)),
        ],
        "exams": [
            {
                "name": "Exam 2",
                "at": (NOW + timedelta(days=3)).isoformat(),
                "scope": ["3.3", "3.4", "3.5", "3.11"],
                "scope_source": "Exam 2 Review: 3.3 to 3.5, 3.11",
                "match": "[In-person] Exam 2*",
                "review": "Exam 2 Review.pdf",
            },
            {"name": "Final", "scope": ["ch2", "ch3"], "match": "Final*"},
        ],
        "exam_checklist": [{"text": "写出过程", "source": "SHOW YOUR WORK"}],
        **over,
    }


def seed(engine: Engine) -> None:
    iid = canvas(engine)
    item(engine, iid, "canvas_course", "c", CODE, course_code=CODE, weighted=True, groups=[])
    for ext, title, kind in [
        ("m1", "Notes.pdf", "File"),
        ("m2", "Math1A-Sec3.4", "ExternalUrl"),  # the teacher's per-section link
        ("m3", "Math 1A Exam 2 Review Solution", "ExternalUrl"),
        ("m4", "Exam 20 Review", "File"),  # not Exam 2's
    ]:
        item(engine, iid, "canvas_material", ext, title, course_code=CODE, kind=kind)
    past = NOW - timedelta(days=5)
    for ext, title, pts, score in [
        ("q1", "[Canvas] Quiz #2 (3.1 to 3.3)", 10, 9.5),  # 95%: 3.1 and 3.3
        ("q0", "[Canvas] Quiz #3 (3.3)", 10, 10),  # a second item for 3.3: verified
        ("q2", "[Canvas] Quiz #4 (3.4)", 10, 5),  # 50%: 3.4 needs review
        ("q3", "Homework3.11", 10, 8),  # 80%: practicing (number glued to the word)
        # the exam names 3.3 to 3.5 in its title: it must not count as practice for them
        ("e2", "[In-person] Exam 2 (3.3 to 3.5)", 100, 40),
    ]:
        item(
            engine,
            iid,
            "canvas_assignment",
            ext,
            title,
            past,
            course_code=CODE,
            points_possible=pts,
            score=score,
            submission_state="graded",
        )


def test_sections_in_titles() -> None:
    order = ["2.1", "2.2", "3.1", "3.9", "3.10", "3.11", "4.1"]
    assert sections_in("Quiz (2.1 to 2.2)", order) == ["2.1", "2.2"]
    assert sections_in("Sections 3.1 to 3.10, and 4.1", order) == ["3.1", "3.9", "3.10", "4.1"]
    assert sections_in("(3.1 to 3.9) and 3.11", order) == ["3.1", "3.9", "3.11"]  # 3.11 intact
    assert sections_in("Sections 3.8 to 3.10", order) == ["3.9", "3.10"]  # 3.8 is not taught
    assert sections_in("3.10 to 3.9", order) == ["3.9", "3.10"]  # reversed
    assert sections_in("Math1A-Sec3.9(part1)", order) == ["3.9"]
    assert sections_in("Exam 2 Review", order) == []
    assert sections_in("Lab 9.9", order) == []


def test_put_and_read_a_map_with_links_and_inferred_mastery(hub) -> None:
    client, engine = hub
    seed(engine)
    r = client.put("/academic/maps/math d001a", json=course_map())
    assert r.status_code == 200, r.text
    assert client.get("/academic/maps").json() == ["MATH D001A"]
    m = client.get("/academic/maps/MATH D001A").json()
    by = {c["key"]: c for c in m["concepts"]}
    assert by["3.4"]["material_url"] == "https://c/m1" and by["3.4"]["page"] == 31
    assert [r["title"] for r in by["3.4"]["resources"]] == ["Math1A-Sec3.4"]
    assert by["3.3"]["resources"] == []
    assert by["3.3"]["mastery"] == {
        "state": "verified",
        "source": "quiz",
        "note": "根据 2 项已评分的练习推断，平均 98%",  # the exam (40%) is not one of them
        "updated_at": None,
    }
    one = by["3.1"]["mastery"]  # one quiz at 95%: a good sign, not proof
    assert one["state"] == "practicing" and "只有 1 项" in one["note"]
    assert by["3.4"]["mastery"]["state"] == "needs_review"
    assert by["3.4"]["mastery"]["note"].startswith("根据 1 项")  # the exam is not counted
    assert by["3.5"]["mastery"]["state"] == "not_tested"  # only the exam names it
    assert by["3.11"]["mastery"]["state"] == "practicing"
    assert by["ch3"]["mastery"] is None and by["3.5"]["prereq_origin"] == "ai"
    exam = next(e for e in m["exams"] if e["name"] == "Exam 2")
    assert exam["days_left"] == 3 and exam["grade"]["percent"] == 40.0
    assert [r["title"] for r in exam["resources"]] == ["Math 1A Exam 2 Review Solution"]
    final = next(e for e in m["exams"] if e["name"] == "Final")
    assert final["scope"] == ["2.3", "3.1", "3.3", "3.4", "3.5", "3.11"]  # chapters expanded
    assert final["grade"] is None  # no Final assignment with a score yet


def test_the_exam_map_orders_weakest_first_and_adds_prerequisites(hub) -> None:
    client, engine = hub
    seed(engine)
    client.put("/academic/maps/MATH D001A", json=course_map())
    e = client.get("/academic/maps/MATH D001A/exams/Exam 2").json()
    assert [s["key"] for s in e["sections"]] == ["3.3", "3.4", "3.5", "3.11"]
    # 3.1 (for 3.3 and 3.4) and 2.3 (for 3.11) are outside the scope; 3.4-chain is inside 3.4
    assert sorted(p["key"] for p in e["prerequisites"]) == ["2.3", "3.1"]
    assert e["suggested"] == ["3.4", "3.5", "3.11"]  # needs review, not tested, practicing
    assert "偏低" in e["why"]["3.4"] and "还没有评分" in e["why"]["3.5"]
    assert "3.3" not in e["why"]  # verified: no need to start there
    assert e["checklist"] == [{"text": "写出过程", "source": "SHOW YOUR WORK"}]
    assert client.get("/academic/maps/MATH D001A/exams/Nope").status_code == 404


def test_the_user_sets_mastery_and_a_new_map_keeps_it(hub) -> None:
    client, engine = hub
    seed(engine)
    client.put("/academic/maps/MATH D001A", json=course_map())
    r = client.put(
        "/academic/maps/MATH D001A/mastery/3.4", json={"state": "verified", "note": "重做了错题"}
    )
    assert r.status_code == 200 and r.json()["source"] == "user"
    client.put(
        "/academic/maps/MATH D001A/mastery/3.3", json={"state": "needs_review", "note": "忘了公式"}
    )
    client.put("/academic/maps/MATH D001A/mastery/3.11", json={"state": "seen"})
    e = client.get("/academic/maps/MATH D001A/exams/Exam 2").json()
    assert e["why"]["3.3"] == "你自己标记为“要复习”：忘了公式"  # the user's words, not a score
    assert e["why"]["3.11"] == "你自己标记为“已接触”"
    assert "3.4" not in e["why"]  # the user says verified
    client.put("/academic/maps/MATH D001A", json=course_map(material="Notes v2.pdf"))
    m = client.get("/academic/maps/MATH D001A").json()
    by = {c["key"]: c for c in m["concepts"]}
    assert by["3.4"]["mastery"]["state"] == "verified"
    assert by["3.4"]["mastery"]["note"] == "重做了错题"
    assert by["3.4"]["material_url"] == ""  # Notes v2.pdf is not synced
    assert client.delete("/academic/maps/MATH D001A/mastery/3.4").status_code == 204
    m = client.get("/academic/maps/MATH D001A").json()
    assert {c["key"]: c for c in m["concepts"]}["3.4"]["mastery"]["source"] == "quiz"
    bad = client.put("/academic/maps/MATH D001A/mastery/9.9", json={"state": "seen"})
    assert bad.status_code == 404
    chapter = client.put("/academic/maps/MATH D001A/mastery/ch3", json={"state": "seen"})
    assert chapter.status_code == 422


def test_a_seen_section_is_suggested_with_a_reason(hub) -> None:
    client, engine = hub
    seed(engine)
    client.put("/academic/maps/MATH D001A", json=course_map())
    client.put("/academic/maps/MATH D001A/mastery/3.3", json={"state": "seen"})
    e = client.get("/academic/maps/MATH D001A/exams/Exam 2").json()
    assert "3.3" in e["suggested"] and "已接触" in e["why"]["3.3"]


@pytest.mark.parametrize(
    "over",
    [
        {"concepts": [{"key": "a", "kind": "section", "title": "x", "parent": "nope"}]},
        {"concepts": [{"key": "a", "kind": "section", "title": "x", "prereq": ["b"]}]},
        {
            "concepts": [
                {"key": "a", "kind": "section", "title": "x"},
                {"key": "a", "kind": "section", "title": "y"},
            ]
        },
        {"exams": [{"name": "E", "scope": ["9.9"], "match": "E"}]},
        {
            "exams": [{"name": "E", "scope": ["3.4-chain"], "match": "E"}]
        },  # a concept, not a section
        {"exams": [{"name": "E", "scope": ["3.4"]}]},  # no title pattern
        {"exams": [{"name": "E", "scope": ["3.4"], "match": "*a*b*c*"}]},  # too many wildcards
        {
            "exams": [
                {"name": "E", "scope": ["3.4"], "match": "E"},
                {"name": "E", "scope": ["3.5"], "match": "F"},
            ]
        },
    ],
)
def test_bad_maps_are_refused(hub, over: dict[str, Any]) -> None:
    client, _ = hub
    assert client.put("/academic/maps/MATH D001A", json=course_map(**over)).status_code == 422


def test_unknown_course_and_mismatched_path(hub) -> None:
    client, _ = hub
    assert client.get("/academic/maps/X 1").status_code == 404
    assert client.put("/academic/maps/OTHER 1", json=course_map()).status_code == 422
    put = client.put("/academic/maps/X 1/mastery/3.4", json={"state": "seen"})
    assert put.status_code == 404


def test_profile_paths_are_normalised_and_wildcards_are_capped(hub) -> None:
    client, _ = hub
    from tests.hub.test_academic import fields

    client.put("/academic/profiles/CIS D022A", json={"fields": fields(), "version": None})
    assert client.get("/academic/profiles/cis  d022a").status_code == 200
    too_many = fields(categories=[{"name": "a", "weight": 100, "match": "*a*b*c*"}])
    r = client.put("/academic/profiles/CIS D022A", json={"fields": too_many, "version": 1})
    assert r.status_code == 422


def test_undated_repeats_in_one_group_are_not_copies(hub) -> None:
    """GPA: two same-title items without due dates in one group stay two items."""
    client, engine = hub
    iid = canvas(engine)
    code = "F26 ENGL C1000 35Y"
    item(
        engine,
        iid,
        "canvas_course",
        "e",
        code,
        course_code=code,
        current_score=None,
        current_grade="",
        weighted=False,
        groups=[{"id": 1, "name": "Discussions"}],
    )
    item(
        engine,
        iid,
        "canvas_assignment",
        "d1",
        "Discussion",
        None,
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
        "d2",
        "Discussion",
        None,
        course_code=code,
        group_id=1,
        points_possible=2,
        score=None,
        missing=True,
        submission_state="unsubmitted",
    )
    course = client.get("/gpa").json()["courses"][0]
    assert [w["title"] for w in course["missing"]] == ["Discussion"]
    assert not any("同名" in n for n in course["notes"])


ECON = "F26 ECON C2002 03Y Prin Macroeconomics"


def test_sections_without_numbers_link_their_work_by_title(hub) -> None:
    client, engine = hub
    iid = canvas(engine)
    item(engine, iid, "canvas_course", "c", ECON, course_code=ECON, weighted=True, groups=[])
    for ext, title in [
        ("m1", "Monetary Policy.doc"),
        ("m2", "Intro: Monetary Policy"),
        ("m3", "Financial Crisis, Panics, and Unconventional Monetary Policy.doc"),
        ("m4", "Exam #2 Study Guide with video"),
    ]:
        item(engine, iid, "canvas_material", ext, title, course_code=ECON, kind="File")
    for ext, title, pts, score in [
        ("h1", "Homework - Monetary  Policy", 10, 9),  # Canvas titles keep stray spaces
        ("h2", "Homework - Financial Crisis, Panics, and Unconventional Monetary Policy", 10, 6),
        ("e2", "Exam #2 - Please don't forget to use a Chrome web browser.", 30, None),
    ]:
        item(
            engine,
            iid,
            "canvas_assignment",
            ext,
            title,
            NOW,
            course_code=ECON,
            points_possible=pts,
            score=score,
        )
    body = {
        "course_code": "ECON C2002",
        "concepts": [
            {"key": "p2", "kind": "chapter", "title": "Before Exam 2"},
            {
                "key": "U7",
                "kind": "section",
                "parent": "p2",
                "title": "Monetary Policy",
                "match": ["Homework - Monetary Policy", "Monetary Policy.doc", "Intro: Monetary*"],
            },
            {
                "key": "U8",
                "kind": "section",
                "parent": "p2",
                "title": "Financial Crisis",
                "match": ["*Financial Crisis, Panics*"],
            },
        ],
        "exams": [{"name": "Exam 2", "scope": ["p2"], "match": "Exam *2 - Please*"}],
    }
    assert client.put("/academic/maps/ECON C2002", json=body).status_code == 200
    by = {c["key"]: c for c in client.get("/academic/maps/ECON C2002").json()["concepts"]}
    assert [a["title"] for a in by["U7"]["assessments"]] == ["Homework - Monetary  Policy"]
    assert sorted(r["title"] for r in by["U7"]["resources"]) == [
        "Intro: Monetary Policy",
        "Monetary Policy.doc",
    ]
    # the whole title must match: "Monetary Policy" does not take the crisis chapter's work
    assert [a["percent"] for a in by["U8"]["assessments"]] == [60.0]
    assert by["U8"]["mastery"]["state"] == "needs_review"
    e = client.get("/academic/maps/ECON C2002/exams/Exam 2").json()
    assert e["suggested"] == ["U8", "U7"]
    assert [r["title"] for r in e["exam"]["resources"]] == ["Exam #2 Study Guide with video"]


def test_title_patterns_are_checked(hub) -> None:
    client, _ = hub
    sec_ = {"key": "a", "kind": "section", "title": "x"}
    for bad in (
        {**sec_, "match": ["*a*b*c*d"]},  # more than three wildcards
        {**sec_, "match": [" "]},
        {"key": "a", "kind": "chapter", "title": "x", "match": ["x"]},
    ):
        r = client.put(
            "/academic/maps/ECON C2002", json={"course_code": "ECON C2002", "concepts": [bad]}
        )
        assert r.status_code == 422, bad
