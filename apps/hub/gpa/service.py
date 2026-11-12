# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""GPA management (ADR 0037): per-course status built from the Canvas items the connector
synced. Nothing here calls Canvas or a model; it only reads and computes.

Canvas's "current" score counts graded work only and is the grade so far. Its "final" score
counts every ungraded assignment as 0, so it is not shown as a grade.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.integrations import service as integrations
from packages.contracts.gpa import (
    Completion,
    CourseView,
    GpaView,
    GradeLine,
    GroupStatus,
    Material,
    WorkItem,
)
from packages.contracts.integrations import SyncedItem

WINDOW = timedelta(days=14)
# Common letter-to-points scale; De Anza's own scale may differ per course syllabus.
POINTS = {
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "C-": 1.7,
    "D+": 1.3,
    "D": 1.0,
    "D-": 0.7,
    "F": 0.0,
}
# Estimated grade lines (the course syllabus is the authority).
LINES = [("A", 90.0), ("B", 80.0), ("C", 70.0)]
_CODE = re.compile(r"\b([A-Z]{2,5})\s+([A-Z]?\d{3,4}[A-Z]?)\b")
GPA_NOTE = "按每门课同样学分、常见字母分换算估算；学分和各课的分数线以学校和教学大纲为准。"


@dataclass
class _Assignment:
    item: SyncedItem

    @property
    def data(self) -> dict[str, Any]:
        return self.item.data

    @property
    def points(self) -> float | None:
        p = self.data.get("points_possible")
        return float(p) if isinstance(p, int | float) and not isinstance(p, bool) else None

    @property
    def score(self) -> float | None:
        s = self.data.get("score")
        return float(s) if isinstance(s, int | float) and not isinstance(s, bool) else None

    @property
    def counts(self) -> bool:
        return not self.data.get("excused") and not self.data.get("omit_from_final")

    def state(self, now: datetime) -> str:
        d = self.data
        if d.get("excused"):
            return "excused"
        if self.score is not None or d.get("submission_state") == "graded":
            return "late" if d.get("late") else "graded"
        if d.get("missing"):
            return "missing"
        if d.get("submission_state") in ("submitted", "pending_review"):
            return "late" if d.get("late") else "submitted"
        due = self.item.starts_at
        if due is not None and due < now:
            return "missing"  # past due, nothing handed in
        return "upcoming" if due is not None else "open"


def course_code(raw: str) -> str:
    m = _CODE.search(raw or "")
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _work(a: _Assignment, groups: dict[int, str], now: datetime) -> WorkItem:
    return WorkItem(
        item_id=a.item.id,
        title=a.item.title,
        due=a.item.starts_at,
        points=a.points,
        group=groups.get(a.data.get("group_id") or -1, ""),
        state=a.state(now),
        score=a.score,
        url=a.item.url,
    )


def _graded_at(a: _Assignment) -> datetime | None:
    raw = a.data.get("graded_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _line(
    label: str, target: float, done_value: float, done_weight: float, left: float
) -> GradeLine:
    """done_value: the course total earned so far (in percent points of the whole course);
    done_weight: how much of the course is graded; left: how much is still to grade."""
    if left <= 0:
        status = (
            "done"
            if done_weight > 0 and done_value / done_weight * 100 >= target
            else "out_of_reach"
        )
        return GradeLine(label=label, target=target, needed=None, status=status)
    needed = (target * (done_weight + left) / 100 - done_value) / left * 100
    if needed <= 0:
        status = "safe"
    elif needed <= 100:
        status = "reachable"
    else:
        status = "out_of_reach"
    return GradeLine(label=label, target=target, needed=round(needed, 1), status=status)


def _course_view(
    course: SyncedItem, assignments: list[_Assignment], materials: list[SyncedItem], now: datetime
) -> CourseView:
    data = course.data
    weighted = bool(data.get("weighted"))
    raw_groups = [
        g for g in data.get("groups") or [] if isinstance(g, dict) and g.get("id") is not None
    ]
    names = {int(g["id"]): str(g.get("name") or "") for g in raw_groups}
    groups: list[GroupStatus] = []
    done_value = done_weight = left = 0.0  # in "percent of the course" units
    for g in raw_groups:
        members = [a for a in assignments if a.data.get("group_id") == g["id"] and a.counts]
        graded = [a for a in members if a.score is not None and a.points]
        earned = sum(a.score or 0.0 for a in graded)
        possible = sum(a.points or 0.0 for a in graded)
        pending = [a for a in members if a.score is None and a.points]
        percent = round(earned / possible * 100, 2) if possible else None
        weight = float(g.get("weight") or 0.0)
        groups.append(
            GroupStatus(
                name=str(g.get("name") or ""),
                weight=weight,
                earned=earned,
                possible=possible,
                percent=percent,
                graded=len(graded),
                total=len(members),
            )
        )
        if weighted:
            if percent is not None:
                # graded share of the group counts now; the ungraded share is still open
                share = possible / (possible + sum(a.points or 0.0 for a in pending))
                done_value += weight * share * percent / 100
                done_weight += weight * share
                left += weight * (1 - share)
            elif weight > 0:
                left += weight
    if not weighted:
        counted = [a for a in assignments if a.counts and a.points]
        graded_points = sum(a.points or 0.0 for a in counted if a.score is not None)
        earned_points = sum(a.score or 0.0 for a in counted if a.score is not None)
        pending_points = sum(a.points or 0.0 for a in counted if a.score is None)
        total = graded_points + pending_points
        if total:
            done_value = earned_points / total * 100
            done_weight = graded_points / total * 100
            left = pending_points / total * 100
    # Canvas's current score is the authority for "so far" (it applies the course's own
    # rules, such as dropped or muted work); our sums only say how much is still ungraded.
    canvas_score = data.get("current_score")
    if isinstance(canvas_score, int | float) and not isinstance(canvas_score, bool) and done_weight:
        done_value = float(canvas_score) * done_weight / 100
    due_so_far = [
        a for a in assignments if a.counts and a.item.starts_at and a.item.starts_at < now
    ]
    states = [a.state(now) for a in due_so_far]
    completion = Completion(
        due_so_far=len(due_so_far),
        done=sum(1 for s in states if s in ("graded", "submitted", "late")),
        missing=sum(1 for s in states if s == "missing"),
        late=sum(1 for s in states if s == "late"),
    )
    work = [_work(a, names, now) for a in assignments]
    missing = sorted((w for w in work if w.state == "missing"), key=lambda w: w.due or now)
    upcoming = sorted(
        (
            w
            for w in work
            if w.state in ("upcoming", "open") and w.due and now <= w.due <= now + WINDOW
        ),
        key=lambda w: w.due or now,
    )
    recent_items = [(a, _graded_at(a)) for a in assignments]
    recent = [
        _work(a, names, now)
        for a, at in sorted(
            ((a, at) for a, at in recent_items if at and now - at <= WINDOW),
            key=lambda x: x[1] or now,
            reverse=True,
        )
    ]
    grade = str(data.get("current_grade") or "")
    score = data.get("current_score")
    return CourseView(
        integration_item_id=course.id,
        code=course_code(str(data.get("course_code") or course.title)) or course.title,
        name=course.title,
        url=course.url,
        current_score=float(score)
        if isinstance(score, int | float) and not isinstance(score, bool)
        else None,
        current_grade=grade,
        grade_points=POINTS.get(grade),
        weighted=weighted,
        groups=groups,
        completion=completion,
        missing=missing,
        upcoming=upcoming,
        recent=recent,
        lines=[
            _line(f"{letter}（{int(t)}%）", t, done_value, done_weight, left) for letter, t in LINES
        ],
        materials=[
            Material(
                title=m.title,
                module=str(m.data.get("module") or ""),
                kind=str(m.data.get("kind") or ""),
                url=m.url,
            )
            for m in sorted(
                materials,
                key=lambda m: (m.data.get("module_position") or 0, m.data.get("position") or 0),
            )
        ],
    )


def _items(session: Session, actor: Actor, item_type: str) -> list[SyncedItem]:
    ids = [i for i, _, _ in integrations.item_index(session, actor, item_type)]
    return list(integrations.items_by_id(session, actor, ids).values())


def view(session: Session, actor: Actor, now: datetime | None = None) -> GpaView:
    """Every credit course (a Canvas course whose code names a department and number)."""
    now = now or datetime.now(UTC)
    courses = [
        c
        for c in _items(session, actor, "canvas_course")
        if course_code(str(c.data.get("course_code") or ""))
    ]
    assignments = _items(session, actor, "canvas_assignment")
    materials = _items(session, actor, "canvas_material")
    views: list[CourseView] = []
    for c in courses:
        code = str(c.data.get("course_code") or "")
        mine = [_Assignment(a) for a in assignments if str(a.data.get("course_code") or "") == code]
        mats = [m for m in materials if str(m.data.get("course_code") or "") == code]
        views.append(_course_view(c, mine, mats, now))
    views.sort(key=lambda v: v.code)
    points = [v.grade_points for v in views if v.grade_points is not None]
    gpa = round(sum(points) / len(points), 2) if points else None
    return GpaView(courses=views, gpa=gpa, gpa_note=GPA_NOTE, generated_at=now)


__all__ = ["course_code", "view"]
