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


def course_map(**over: Any) -> dict[str, Any]:
    sec = lambda key, parent, title, page, prereq=(): {  # noqa: E731
        "key": key,
        "kind": "section",
        "parent": parent,
        "title": title,
        "page": page,
        "prereq": list(prereq),
    }
    return {
        "course_code": "MATH D001A",
        "material": "Notes.pdf",
        "concepts": [
            {"key": "ch2", "kind": "chapter", "title": "Limits"},
            sec("2.3", "ch2", "Limit laws", 6),
            {"key": "ch3", "kind": "chapter", "title": "Rules"},
            sec("3.1", "ch3", "Power rule", 23),
            sec("3.3", "ch3", "Trig", 28, ["3.1"]),
            sec("3.4", "ch3", "Chain rule", 31, ["3.1", "3.3"]),
            {"key": "3.4-chain", "kind": "concept", "parent": "3.4", "title": "Chain", "page": 31},
            sec("3.5", "ch3", "Implicit", 33, ["3.4-chain"]),
            sec("3.11", "ch3", "Hyperbolic", 47, ["2.3"]),
        ],
        "exams": [
            {
                "name": "Exam 2",
                "at": (NOW + timedelta(days=3)).isoformat(),
                "scope": ["3.3", "3.4", "3.5", "3.11"],
                "scope_source": "Exam 2 Review: 3.3 to 3.5, 3.11",
                "match": "[In-person] Exam 2",
                "review": "Exam 2 Review.pdf",
            },
            {"name": "Final", "scope": ["ch2", "ch3"]},
        ],
        "exam_checklist": [{"text": "写出过程", "source": "SHOW YOUR WORK"}],
        **over,
    }


def seed(engine: Engine) -> None:
    iid = canvas(engine)
    item(engine, iid, "canvas_course", "c", CODE, course_code=CODE, weighted=True, groups=[])
    item(engine, iid, "canvas_material", "m1", "Notes.pdf", course_code=CODE, kind="File")
    past = NOW - timedelta(days=5)
    for ext, title, pts, score in [
        ("q1", "[Canvas] Quiz #2 (3.1 to 3.3)", 10, 9.5),  # 95%: 3.1 and 3.3
        ("q2", "[Canvas] Quiz #4 (3.4)", 10, 5),  # 50%: 3.4 needs review
        ("q3", "Homework 3.11", 10, 8),  # 80%: practicing
        ("e2", "[In-person] Exam 2", 100, None),  # the exam itself, not practice
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
            submission_state="graded" if score else "",
        )


def test_sections_in_titles() -> None:
    order = ["2.1", "2.2", "3.1", "3.10", "3.11", "4.1"]
    assert sections_in("Quiz (2.1 to 2.2)", order) == ["2.1", "2.2"]
    assert sections_in("Sections 3.1 to 3.10, and 4.1", order) == ["3.1", "3.10", "4.1"]
    assert sections_in("(3.1 to 3.10) and 3.11", order) == ["3.1", "3.10", "3.11"]  # 3.11 intact
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
    assert [a["title"] for a in by["3.3"]["assessments"]] == ["[Canvas] Quiz #2 (3.1 to 3.3)"]
    assert by["3.3"]["mastery"] == {
        "state": "verified",
        "source": "quiz",
        "note": "根据 1 项已评分的练习推断，平均 95%",
        "updated_at": None,
    }
    assert by["3.4"]["mastery"]["state"] == "needs_review"
    assert by["3.11"]["mastery"]["state"] == "practicing"
    assert by["2.3"]["mastery"] == {
        "state": "not_tested",
        "source": "none",
        "note": "还没有评分的练习",
        "updated_at": None,
    }
    assert by["ch3"]["mastery"] is None and by["3.5"]["prereq_origin"] == "ai"
    exam = next(e for e in m["exams"] if e["name"] == "Exam 2")
    assert exam["days_left"] == 3 and exam["grade"]["title"] == "[In-person] Exam 2"
    assert all("Exam 2" not in a["title"] for c in m["concepts"] for a in c["assessments"])
    final = next(e for e in m["exams"] if e["name"] == "Final")
    assert final["scope"] == ["2.3", "3.1", "3.3", "3.4", "3.5", "3.11"]  # chapters expanded


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
    client.put("/academic/maps/MATH D001A", json=course_map(material="Notes v2.pdf"))
    m = client.get("/academic/maps/MATH D001A").json()
    by = {c["key"]: c for c in m["concepts"]}
    assert (
        by["3.4"]["mastery"]["state"] == "verified" and by["3.4"]["mastery"]["note"] == "重做了错题"
    )
    assert by["3.4"]["material_url"] == ""  # Notes v2.pdf is not synced
    assert client.delete("/academic/maps/MATH D001A/mastery/3.4").status_code == 204
    m = client.get("/academic/maps/MATH D001A").json()
    assert {c["key"]: c for c in m["concepts"]}["3.4"]["mastery"]["source"] == "quiz"
    bad = client.put("/academic/maps/MATH D001A/mastery/9.9", json={"state": "seen"})
    assert bad.status_code == 404


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
        {"exams": [{"name": "E", "scope": ["9.9"]}]},
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
