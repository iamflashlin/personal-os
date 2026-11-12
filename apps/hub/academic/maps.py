# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""The course knowledge map (ADR 0041): structure, assessment links, mastery, exam maps.

Assessments are linked to sections by the section numbers in their Canvas titles
("Quiz #4 (3.2 to 3.4)", "Sections 3.5 to 3.11, and 4.1"); exams by their own title
pattern. Mastery the user did not set is inferred from those scores and says so; with no
score it is "not tested", never a guess."""

import math
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.academic.models import ConceptMasteryRow, CourseMapRow
from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, NotFound
from apps.hub.integrations import service as integrations
from packages.contracts.academic import TITLE_MAX, canvas_course_code, normal_code, title_pattern
from packages.contracts.course_map import (
    CheckItem,
    ConceptIn,
    ConceptView,
    CourseMap,
    Evidence,
    ExamIn,
    ExamMap,
    ExamView,
    MapIn,
    MasteryView,
    MasteryWrite,
    Resource,
)
from packages.contracts.integrations import SyncedItem

_SECTION = re.compile(r"\b(\d{1,2}\.\d{1,2})\b")
_RANGE = re.compile(r"\b(\d{1,2}\.\d{1,2})\s*(?:to|-|–|through)\s*(\d{1,2}\.\d{1,2})\b", re.I)
VERIFIED, PRACTICING = 90.0, 70.0  # average percent on linked graded work
_ORDER = {"needs_review": 0, "not_tested": 1, "seen": 2, "practicing": 3, "verified": 4}


def _row(session: Session, actor: Actor, code: str) -> CourseMapRow | None:
    return session.scalar(
        select(CourseMapRow).where(
            CourseMapRow.owner_id == actor.owner_id, CourseMapRow.code == normal_code(code)
        )
    )


def put_map(session: Session, actor: Actor, new: MapIn, origin: str = "import") -> int:
    """Create or replace a course's map. Mastery rows stay: they belong to the user."""
    code = normal_code(new.course_code)
    body = {
        "material": new.material,
        "note": new.note,
        "concepts": [c.model_dump(mode="json") for c in new.concepts],
        "exams": [e.model_dump(mode="json") for e in new.exams],
        "checklist": [c.model_dump(mode="json") for c in new.exam_checklist],
    }
    row = _row(session, actor, code)

    def op() -> audit.Outcome[int]:
        nonlocal row
        if row is None:
            row = CourseMapRow(owner_id=actor.owner_id, source=origin, version=1, code=code, **body)
            session.add(row)
        else:
            for k, v in body.items():
                setattr(row, k, v)
            row.source = origin
        try:
            session.flush()
        except IntegrityError:
            raise Conflict("这门课的知识地图刚被写入，请再试一次") from None
        return audit.Outcome(row.id, row.version, {"code": code, "concepts": len(new.concepts)})

    return audit.audited(session, actor, "course_map", "put", row.id if row else None, {}, op)


def map_codes(session: Session, actor: Actor) -> list[str]:
    return list(
        session.scalars(
            select(CourseMapRow.code)
            .where(CourseMapRow.owner_id == actor.owner_id)
            .order_by(CourseMapRow.code)
        )
    )


def _canvas(session: Session, actor: Actor, item_type: str, code: str) -> list[SyncedItem]:
    ids = [i for i, _, _ in integrations.item_index(session, actor, item_type)]
    items = integrations.items_by_id(session, actor, ids).values()
    return [i for i in items if canvas_course_code(str(i.data.get("course_code") or "")) == code]


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _evidence(a: SyncedItem) -> Evidence:
    score, points = _num(a.data.get("score")), _num(a.data.get("points_possible"))
    percent = round(score / points * 100, 1) if score is not None and points else None
    return Evidence(
        title=a.title, score=score, points=points, percent=percent, due=a.starts_at, url=a.url
    )


def sections_in(title: str, order: list[str]) -> list[str]:
    """The section keys a title names, ranges expanded in teaching order."""
    found: list[str] = []
    for lo, hi in _RANGE.findall(title):
        if lo in order and hi in order and order.index(lo) <= order.index(hi):
            found.extend(order[order.index(lo) : order.index(hi) + 1])
    rest = _RANGE.sub(" ", title)  # the single numbers left once the ranges are out
    found.extend(k for k in _SECTION.findall(rest) if k in order)
    return list(dict.fromkeys(found))


def _user_view(row: ConceptMasteryRow) -> MasteryView:
    return MasteryView.model_validate(
        {"state": row.state, "source": "user", "note": row.note, "updated_at": row.updated_at}
    )


def _mastery(key: str, rows: dict[str, ConceptMasteryRow], evidence: list[Evidence]) -> MasteryView:
    row = rows.get(key)
    if row is not None:
        return _user_view(row)
    scored = [e.percent for e in evidence if e.percent is not None]
    if not scored:
        return MasteryView(
            state="not_tested", source="none", note="还没有评分的练习", updated_at=None
        )
    avg = sum(scored) / len(scored)
    state = "verified" if avg >= VERIFIED else "practicing" if avg >= PRACTICING else "needs_review"
    note = f"根据 {len(scored)} 项已评分的练习推断，平均 {avg:.0f}%"
    return MasteryView(state=state, source="quiz", note=note, updated_at=None)


def _spaced(title: str) -> str:
    """'Math1A-Sec3.9(part1)' -> 'Math1A-Sec 3.9 (part1)': lets the section pattern see
    numbers glued to letters."""
    return re.sub(r"(\d+\.\d+)", r" \1 ", title)


def _title_key(title: str) -> str:
    return " ".join(title.casefold().replace("#", " ").split())


def _material_url(materials: list[SyncedItem], name: str) -> str:
    if not name:
        return ""
    for m in materials:
        if m.title.strip() == name.strip():
            return m.url
    return ""


def _build(
    session: Session, actor: Actor, code: str, now: datetime
) -> tuple[CourseMapRow, list[ConceptView], list[ExamView], list[CheckItem]]:
    row = _row(session, actor, code)
    if row is None:
        raise NotFound("这门课还没有知识地图")
    concepts = [ConceptIn.model_validate(c) for c in row.concepts]
    exams = [ExamIn.model_validate(e) for e in row.exams]
    order = [c.key for c in concepts if c.kind == "section"]
    assignments = _canvas(session, actor, "canvas_assignment", row.code)
    materials = _canvas(session, actor, "canvas_material", row.code)
    exam_titles = [title_pattern(e.match) for e in exams if e.match]
    linked: dict[str, list[Evidence]] = {k: [] for k in order}
    resources: dict[str, list[Resource]] = {k: [] for k in order}
    for m in materials:
        res = Resource(title=m.title, kind=str(m.data.get("kind") or ""), url=m.url)
        for key in sections_in(_spaced(m.title), order):
            resources[key].append(res)
    for a in assignments:
        title = a.title.strip()[:TITLE_MAX]
        if any(p.fullmatch(title) for p in exam_titles):
            continue  # an exam covers its scope; it is shown on the exam, not as practice
        for key in sections_in(title, order):
            linked[key].append(_evidence(a))
    mastery = {
        m.key: m
        for m in session.scalars(
            select(ConceptMasteryRow).where(
                ConceptMasteryRow.owner_id == actor.owner_id, ConceptMasteryRow.code == row.code
            )
        )
    }
    notes_url = _material_url(materials, row.material)
    views = [
        ConceptView(
            key=c.key,
            kind=c.kind,
            parent=c.parent,
            title=c.title,
            title_zh=c.title_zh,
            page=c.page,
            material_url=notes_url if c.page else "",
            prereq=c.prereq,
            prereq_origin=c.prereq_origin,
            origin=c.origin,
            assessments=linked.get(c.key, []) if c.kind == "section" else [],
            resources=resources.get(c.key, []) if c.kind == "section" else [],
            mastery=None
            if c.kind == "chapter"
            else _mastery(c.key, mastery, linked.get(c.key, [])),
        )
        for c in concepts
    ]
    children = {c.parent: [] for c in concepts}
    for c in concepts:
        children.setdefault(c.parent, []).append(c.key)
    exam_views = []
    for e in exams:
        scope: list[str] = []
        for k in e.scope:
            scope.extend(children.get(k, []) if k.startswith("ch") or k not in order else [k])
        scope = [k for k in dict.fromkeys(scope) if k in order]
        grade = None
        if e.match:
            p = title_pattern(e.match)
            graded = [_evidence(a) for a in assignments if p.fullmatch(a.title.strip()[:TITLE_MAX])]
            grade = next((g for g in graded if g.score is not None), graded[0] if graded else None)
        days = None
        if e.at is not None:
            days = math.ceil((e.at - now).total_seconds() / 86400)
        exam_views.append(
            ExamView(
                name=e.name,
                at=e.at,
                days_left=days,
                scope=scope,
                scope_source=e.scope_source,
                review=e.review,
                review_url=_material_url(materials, e.review),
                resources=[
                    Resource(title=m.title, kind=str(m.data.get("kind") or ""), url=m.url)
                    for m in materials
                    if _title_key(e.name) in _title_key(m.title)
                ],
                grade=grade,
            )
        )
    checklist = [CheckItem.model_validate(c) for c in row.checklist]
    return row, views, exam_views, checklist


def course_map(session: Session, actor: Actor, code: str, now: datetime | None = None) -> CourseMap:
    row, views, exams, checklist = _build(session, actor, code, now or datetime.now(UTC))
    return CourseMap(
        course_code=row.code,
        material=row.material,
        note=row.note,
        concepts=views,
        exams=exams,
        checklist=checklist,
    )


def exam_map(
    session: Session, actor: Actor, code: str, name: str, now: datetime | None = None
) -> ExamMap:
    row, views, exams, checklist = _build(session, actor, code, now or datetime.now(UTC))
    exam = next((e for e in exams if e.name == name), None)
    if exam is None:
        raise NotFound("没有这场考试")
    by_key = {v.key: v for v in views}
    sections = [by_key[k] for k in exam.scope]
    scope = set(exam.scope)
    # concepts inside a section count as in scope too
    inside = scope | {v.key for v in views if v.parent in scope}
    needed: list[str] = []
    for s in sections:
        for p in s.prereq:
            target = by_key.get(p)
            if target is None:
                continue
            owner = p if target.kind != "concept" else target.parent
            if owner not in inside and p not in inside:
                needed.append(p)
    prerequisites = [by_key[k] for k in dict.fromkeys(needed)]

    def rank(v: ConceptView) -> tuple[int, float]:
        m = v.mastery
        scored = [e.percent for e in v.assessments if e.percent is not None]
        return (_ORDER.get(m.state if m else "not_tested", 1), min(scored) if scored else 0.0)

    ordered = sorted(sections, key=rank)
    why = {}
    for v in ordered:
        m = v.mastery
        if m is None:
            continue
        if m.state == "needs_review":
            why[v.key] = f"练习成绩偏低：{m.note}"
        elif m.state == "not_tested":
            why[v.key] = "还没有评分的练习，不知道掌握得怎样"
        elif m.state == "practicing":
            why[v.key] = f"还不稳：{m.note}"
    suggested = [v.key for v in ordered if v.key in why]
    return ExamMap(
        course_code=row.code,
        exam=exam,
        sections=sections,
        prerequisites=prerequisites,
        suggested=suggested,
        why=why,
        checklist=checklist,
    )


def set_mastery(
    session: Session, actor: Actor, code: str, key: str, new: MasteryWrite, now: datetime
) -> MasteryView:
    row = _row(session, actor, code)
    if row is None:
        raise NotFound("这门课还没有知识地图")
    if key not in {c["key"] for c in row.concepts}:
        raise NotFound("知识地图里没有这一项")
    current = session.scalar(
        select(ConceptMasteryRow).where(
            ConceptMasteryRow.owner_id == actor.owner_id,
            ConceptMasteryRow.code == row.code,
            ConceptMasteryRow.key == key,
        )
    )

    def op() -> audit.Outcome[MasteryView]:
        nonlocal current
        if current is None:
            current = ConceptMasteryRow(
                owner_id=actor.owner_id, source="user", version=1, code=row.code, key=key
            )
            session.add(current)
        current.state = new.state
        current.note = new.note
        session.flush()
        view = _user_view(current)
        return audit.Outcome(current.id, view, {"code": row.code, "key": key, "state": new.state})

    return audit.audited(session, actor, "concept_mastery", "set", None, {}, op)


def clear_mastery(session: Session, actor: Actor, code: str, key: str) -> None:
    """Back to the inferred state (or not tested)."""
    current = session.scalar(
        select(ConceptMasteryRow).where(
            ConceptMasteryRow.owner_id == actor.owner_id,
            ConceptMasteryRow.code == normal_code(code),
            ConceptMasteryRow.key == key,
        )
    )
    if current is None:
        return
    target = current

    def op() -> audit.Outcome[None]:
        session.delete(target)
        session.flush()
        return audit.Outcome(target.id, None, {"key": key})

    audit.audited(session, actor, "concept_mastery", "clear", target.id, {}, op)


__all__ = [
    "clear_mastery",
    "course_map",
    "exam_map",
    "map_codes",
    "put_map",
    "sections_in",
    "set_mastery",
]
