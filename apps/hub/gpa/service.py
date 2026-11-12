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

from apps.hub.academic import service as academic
from apps.hub.core.domain import Actor
from apps.hub.integrations import service as integrations
from packages.contracts.academic import (
    GRADE_POINTS,
    TITLE_MAX,
    CourseProfile,
    letter_for,
    title_pattern,
)
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
GPA_NOTE_UNITS = (  # shown when every graded course has units
    "按各课学分加权；有规则卡的课用大纲的分数线，"
    "绩点按 De Anza 规定（A+ 和 A 都是 4.0，A- 是 3.7）。"
)
LINES_SHOWN = 4  # grade lines per course, around the current letter


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
            # Past due with nothing handed in, but Canvas does not call it missing: in-class,
            # paper or no-submission work (exams, participation) that is not graded yet.
            return "awaiting_grade"
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
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


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
    # Rounded first, so the status agrees with the number shown (100.0 is reachable).
    needed = round((target * (done_weight + left) / 100 - done_value) / left * 100, 1)
    if needed <= 0:
        status = "safe"
    elif needed <= 100:
        status = "reachable"
    else:
        status = "out_of_reach"
    return GradeLine(label=label, target=target, needed=needed, status=status)


def _title_key(title: str) -> str:
    return " ".join(title.casefold().split())


def _drop_duplicates(
    assignments: list[_Assignment], now: datetime
) -> tuple[list[_Assignment], list[str]]:
    """A missing item that is a copy of handed-in work is left out instead of counting a 0:
    combined classes import the same work twice, into another group and sometimes with other
    points. A copy has the same title and sits in another Canvas group, or has the same
    points and due time in the same group. A weekly "Discussion" in one group with its own
    due date is not a copy."""
    done = [a for a in assignments if a.state(now) in ("graded", "submitted", "late")]
    keep, dupes = [], []
    for a in assignments:
        copy = a.state(now) == "missing" and any(
            _title_key(d.item.title) == _title_key(a.item.title)
            and (
                d.data.get("group_id") != a.data.get("group_id")  # imported into another group
                or (
                    d.points == a.points
                    and a.item.starts_at is not None
                    and d.item.starts_at == a.item.starts_at
                )
            )
            for d in done
        )
        if copy:
            dupes.append(a.item.title.strip())
        else:
            keep.append(a)
    return keep, dupes


def _syllabus_totals(
    profile: CourseProfile, assignments: list[_Assignment], groups: dict[int, str]
) -> tuple[float, float, float, float, float | None, list[str]]:
    """The syllabus's own categories over Canvas's assignments (e.g. CIS, where Canvas has
    one unweighted group).

    Returns, in percent of the whole course: the graded, missing and open weight and the
    weighted earned part (for the grade lines: what the rest must average). Also returns the
    percent so far the way syllabi and Canvas mean it: each category's average (missing work
    as 0) times its weight, over the categories that have graded or missing work."""
    graded_w = missing_w = left = computed = 0.0
    avg_sum = avg_w = 0.0
    used: set[str] = set()
    for cat in profile.categories:
        pattern = title_pattern(cat.match) if cat.match else None
        members = [
            a
            for a in assignments
            if a.counts
            and a.item.id not in used
            and (
                pattern.fullmatch(a.item.title.strip()[:TITLE_MAX]) is not None
                if pattern
                else groups.get(a.data.get("group_id") or -1, "") == cat.name
            )
        ]
        used.update(a.item.id for a in members)
        graded = [a for a in members if a.score is not None and a.points]
        possible = sum(a.points or 0.0 for a in graded)
        earned = sum(a.score or 0.0 for a in graded)
        missing_pts = sum(
            a.points or 0.0
            for a in members
            if a.score is None and a.data.get("missing") and a.points
        )
        open_pts = sum(
            a.points or 0.0
            for a in members
            if a.score is None and not a.data.get("missing") and a.points
        )
        total = possible + missing_pts + open_pts
        if possible + missing_pts:
            avg_sum += cat.weight * earned / (possible + missing_pts)
            avg_w += cat.weight
        if total:
            graded_w += cat.weight * possible / total
            missing_w += cat.weight * missing_pts / total
            left += cat.weight * open_pts / total
            computed += cat.weight * earned / total
        else:
            left += cat.weight
    stray = [a for a in assignments if a.counts and a.points and a.item.id not in used]
    notes = (
        [
            f"有 {len(stray)} 项作业不属于大纲的任何评分类别，没有计入："
            + "、".join(a.item.title for a in stray[:5])
        ]
        if stray
        else []
    )
    so_far = round(avg_sum / avg_w * 100, 2) if avg_w else None
    return graded_w, missing_w, left, computed, so_far, notes


def _targets(profile: CourseProfile | None, percent: float | None) -> list[tuple[str, float]]:
    """The grade lines worth showing: around the current letter (two above, one below), so a
    B student sees B+ and A-, not only A+ and A. F is never a target."""
    if not profile or not profile.scale:
        return LINES
    bands = [b for b in profile.scale if b.min > 0]
    if percent is None:
        return [(b.letter, b.min) for b in bands[:LINES_SHOWN]]
    at = next((i for i, b in enumerate(bands) if percent >= b.min), len(bands))
    start = max(0, at - 2)
    return [(b.letter, b.min) for b in bands[start : start + LINES_SHOWN]]


def _course_view(
    course: SyncedItem,
    assignments: list[_Assignment],
    materials: list[SyncedItem],
    now: datetime,
    profile: CourseProfile | None = None,
) -> CourseView:
    assignments, dupes = _drop_duplicates(assignments, now)
    data = course.data
    weighted = bool(data.get("weighted"))
    raw_groups = [
        g for g in data.get("groups") or [] if isinstance(g, dict) and g.get("id") is not None
    ]
    names = {int(g["id"]): str(g.get("name") or "") for g in raw_groups}
    groups: list[GroupStatus] = []
    # In "percent of the course" units: graded and missing work (missing counts as 0, as
    # Canvas usually scores it), and what is still open to be graded.
    graded_w = missing_w = left = computed = 0.0
    for g in raw_groups:
        members = [a for a in assignments if a.data.get("group_id") == g["id"] and a.counts]
        graded = [a for a in members if a.score is not None and a.points]
        earned = sum(a.score or 0.0 for a in graded)
        possible = sum(a.points or 0.0 for a in graded)
        missing_pts = sum(
            a.points or 0.0
            for a in members
            if a.score is None and a.data.get("missing") and a.points
        )
        open_pts = sum(
            a.points or 0.0
            for a in members
            if a.score is None and not a.data.get("missing") and a.points
        )
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
        group_pts = possible + missing_pts + open_pts
        if weighted and weight > 0:
            if group_pts:
                graded_w += weight * possible / group_pts
                missing_w += weight * missing_pts / group_pts
                left += weight * open_pts / group_pts
                computed += weight * earned / group_pts
            else:
                left += weight  # nothing listed yet (e.g. the final exam): all still open
    if not weighted:
        counted = [a for a in assignments if a.counts and a.points]
        graded_pts = sum(a.points or 0.0 for a in counted if a.score is not None)
        earned_pts = sum(a.score or 0.0 for a in counted if a.score is not None)
        missing_pts = sum(
            a.points or 0.0 for a in counted if a.score is None and a.data.get("missing")
        )
        open_pts = sum(
            a.points or 0.0 for a in counted if a.score is None and not a.data.get("missing")
        )
        total = graded_pts + missing_pts + open_pts
        if total:
            graded_w, missing_w = graded_pts / total * 100, missing_pts / total * 100
            left, computed = open_pts / total * 100, earned_pts / total * 100
    # Canvas's current score is the authority for the graded part: it applies the course's
    # own rules (dropped or muted work). It re-weights over the groups with graded work, so
    # scaling it by our graded share is an approximation. Missing work adds 0.
    canvas_score = data.get("current_score")
    notes: list[str] = []
    if dupes:
        notes.append(
            f"有 {len(dupes)} 项缺交和已交的作业同名，像是合班课的重复项，没算成 0（待确认）："
            + "、".join(dupes[:5])
        )
    own = bool(profile and profile.categories)
    so_far: float | None = None
    if own and profile is not None:
        graded_w, missing_w, left, computed, so_far, cat_notes = _syllabus_totals(
            profile, assignments, names
        )
        notes.extend(cat_notes)
    elif isinstance(canvas_score, int | float) and not isinstance(canvas_score, bool) and graded_w:
        computed = float(canvas_score) * graded_w / 100
    done_value, done_weight = computed, graded_w + missing_w
    due_so_far = [
        a for a in assignments if a.counts and a.item.starts_at and a.item.starts_at < now
    ]
    states = [a.state(now) for a in due_so_far]
    states = [st for st in states if st != "awaiting_grade"]  # neither done nor missing
    completion = Completion(
        due_so_far=len(states),
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
    canvas = (
        float(score) if isinstance(score, int | float) and not isinstance(score, bool) else None
    )
    # The course percent so far counts missing work as 0, like the grade lines do, even
    # when Canvas's current score leaves it out. With own categories it is each category's
    # average times its weight (the syllabus's meaning).
    percent = round(done_value / done_weight * 100, 2) if done_weight else None
    if own:
        percent = so_far
        basis = "syllabus" if percent is not None else "none"
    else:
        if percent is None:
            percent = canvas
        basis = "canvas" if percent is not None else "none"
        if canvas is not None and percent is not None and canvas - percent >= 0.5:
            notes.append(
                f"Canvas 的当前分 {canvas:g}% 没把 {len(missing)} 份缺交算成 0；"
                f"算上缺交是 {percent:g}%"
            )
    if profile and profile.scale and percent is not None:
        letter, letter_source = letter_for(profile.scale, percent) or "", "syllabus"
        if grade and letter and grade != letter:
            notes.append(
                f"Canvas 显示 {grade}，按大纲的分数线是 {letter}（以大纲为准，可向老师确认）"
            )
    else:
        letter, letter_source = grade, ("canvas" if grade else "")
    if (
        profile
        and own
        and canvas is not None
        and percent is not None
        and abs(canvas - percent) >= 1
    ):
        notes.append(
            f"Canvas 的总分是 {canvas:g}%，按大纲的类别和权重算是 {percent:g}%"
            "（Canvas 里没设这些类别的权重）"
        )
    if profile:
        notes.extend(f"待确认：{q}" for q in profile.open_questions)
    targets = _targets(profile, percent)
    return CourseView(
        integration_item_id=course.id,
        code=course_code(str(data.get("course_code") or course.title)) or course.title,
        name=course.title,
        url=course.url,
        current_score=canvas,
        current_grade=grade,
        percent=percent,
        basis=basis,
        letter=letter,
        letter_source=letter_source,
        units=profile.units if profile else None,
        profile_confirmed=None if profile is None else profile.confirmed_at is not None,
        notes=notes,
        grade_points=(GRADE_POINTS if letter_source == "syllabus" else POINTS).get(letter),
        weighted=weighted,
        groups=groups,
        completion=completion,
        missing=missing,
        upcoming=upcoming,
        recent=recent,
        lines=[]
        if done_weight + left <= 0
        else [_line(f"{name}（{t:g}%）", t, done_value, done_weight, left) for name, t in targets],
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
    by_code = {p.code: p for p in academic.profiles(session, actor)}
    materials = _items(session, actor, "canvas_material")
    views: list[CourseView] = []
    for c in courses:
        code = str(c.data.get("course_code") or "")
        mine = [_Assignment(a) for a in assignments if str(a.data.get("course_code") or "") == code]
        mats = [m for m in materials if str(m.data.get("course_code") or "") == code]
        views.append(_course_view(c, mine, mats, now, by_code.get(course_code(code))))
    views.sort(key=lambda v: v.code)
    graded = [v for v in views if v.grade_points is not None]
    weighted = bool(graded) and all(v.units for v in graded)
    if weighted:
        units = sum(v.units or 0.0 for v in graded)
        gpa = round(sum((v.grade_points or 0.0) * (v.units or 0.0) for v in graded) / units, 2)
    else:
        units = None
        points = [v.grade_points or 0.0 for v in graded]
        gpa = round(sum(points) / len(points), 2) if points else None
    return GpaView(
        courses=views,
        gpa=gpa,
        gpa_weighted=weighted,
        units_total=units,
        gpa_note=GPA_NOTE_UNITS if weighted else GPA_NOTE,
        generated_at=now,
    )


__all__ = ["course_code", "view"]
