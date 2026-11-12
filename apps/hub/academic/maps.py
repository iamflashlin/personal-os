# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""The course knowledge map (ADR 0041): structure, assessment links, mastery, exam maps.

Assessments are linked to sections by the section numbers in their Canvas titles
("Quiz #4 (3.2 to 3.4)", "Sections 3.5 to 3.11, and 4.1"), or by the section's own title
patterns when the course does not number its work; exams by their own title pattern.
Mastery the user did not set is inferred from those scores and says so; with no score it
is "not tested", never a guess."""

import math
import re
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.academic.models import ConceptMasteryRow, CourseMapRow
from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.integrations import service as integrations
from packages.contracts.academic import TITLE_MAX, canvas_course_code, normal_code, title_pattern
from packages.contracts.course_map import (
    AssessmentEvidence,
    CheckItem,
    ConceptIn,
    ConceptView,
    CourseMap,
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
VERIFIED_MIN_ITEMS = 2  # one good quiz is a good sign, not proof
_ORDER = {"needs_review": 0, "not_tested": 1, "seen": 2, "practicing": 3, "verified": 4}
MASTERY_ZH = {
    "not_tested": "未测试",
    "seen": "已接触",
    "practicing": "还不稳",
    "verified": "已掌握",
    "needs_review": "要复习",
}


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


def _evidence(a: SyncedItem) -> AssessmentEvidence:
    score, points = _num(a.data.get("score")), _num(a.data.get("points_possible"))
    percent = round(score / points * 100, 1) if score is not None and points else None
    return AssessmentEvidence(
        title=a.title, score=score, points=points, percent=percent, due=a.starts_at, url=a.url
    )


def _num_key(key: str) -> tuple[int, int] | None:
    parts = key.split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def sections_in(title: str, order: list[str]) -> list[str]:
    """The section keys a title names. A range takes every section of the map that falls
    inside it by number, so "3.8 to 3.10" still covers 3.9 and 3.10 when 3.8 is not taught;
    a reversed range is read the right way round."""
    title = _spaced(title)
    found: list[str] = []
    for lo, hi in _RANGE.findall(title):
        a, b = _num_key(lo), _num_key(hi)
        if a is None or b is None:
            continue
        a, b = min(a, b), max(a, b)
        found.extend(k for k in order if (n := _num_key(k)) is not None and a <= n <= b)
    rest = _RANGE.sub(" ", title)  # the single numbers left once the ranges are out
    found.extend(k for k in _SECTION.findall(rest) if k in order)
    return list(dict.fromkeys(found))


def _norm(title: str) -> str:
    """The form every title pattern is matched on: Canvas titles keep stray spaces."""
    return " ".join(title.split())[:TITLE_MAX]


def _linker(concepts: list[ConceptIn]) -> Callable[[str], list[str]]:
    """title -> the section keys it belongs to: by number, then by the sections' patterns."""
    order = [c.key for c in concepts if c.kind == "section"]
    patterns = [(c.key, [title_pattern(p) for p in c.match]) for c in concepts if c.match]

    def keys(title: str) -> list[str]:
        title = _norm(title)
        found = sections_in(title, order)
        found.extend(k for k, ps in patterns if any(p.fullmatch(title) for p in ps))
        return list(dict.fromkeys(found))

    return keys


def _user_view(row: ConceptMasteryRow) -> MasteryView:
    return MasteryView.model_validate(
        {"state": row.state, "source": "user", "note": row.note, "updated_at": row.updated_at}
    )


def _mastery(
    key: str, rows: dict[str, ConceptMasteryRow], evidence: list[AssessmentEvidence]
) -> MasteryView:
    row = rows.get(key)
    if row is not None:
        return _user_view(row)
    scored = [e.percent for e in evidence if e.percent is not None]
    if not scored:
        return MasteryView(
            state="not_tested", source="none", note="还没有评分的练习", updated_at=None
        )
    avg = sum(scored) / len(scored)
    if avg >= VERIFIED and len(scored) >= VERIFIED_MIN_ITEMS:
        state = "verified"
    elif avg >= PRACTICING:
        state = "practicing"
    else:
        state = "needs_review"
    note = f"根据 {len(scored)} 项已评分的练习推断，平均 {avg:.0f}%"
    if avg >= VERIFIED and len(scored) < VERIFIED_MIN_ITEMS:
        note += "（只有 1 项，再做一次练习才算已掌握）"
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
    exam_titles = [title_pattern(_norm(e.match)) for e in exams if e.match]
    linked: dict[str, list[AssessmentEvidence]] = {k: [] for k in order}
    resources: dict[str, list[Resource]] = {k: [] for k in order}
    keys_of = _linker(concepts)
    for m in materials:
        res = Resource(title=m.title, kind=str(m.data.get("kind") or ""), url=m.url)
        for key in keys_of(m.title):
            resources[key].append(res)
    for a in assignments:
        title = _norm(a.title)
        if any(p.fullmatch(title) for p in exam_titles):
            continue  # an exam covers its scope; it is shown on the exam, not as practice
        for key in keys_of(title):
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
    kinds = {c.key: c.kind for c in concepts}
    exam_views = []
    for e in exams:
        scope: list[str] = []
        for k in e.scope:
            scope.extend(children.get(k, []) if kinds.get(k) == "chapter" else [k])
        scope = [k for k in dict.fromkeys(scope) if k in order]
        grade = None
        if e.match:
            p = title_pattern(_norm(e.match))
            graded = [_evidence(a) for a in assignments if p.fullmatch(_norm(a.title))]
            grade = next((g for g in graded if g.score is not None), None)
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
                    if re.search(
                        rf"(?<!\w){re.escape(_title_key(e.name))}(?!\w)", _title_key(m.title)
                    )
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
        if m.source == "user":
            if m.state != "verified":
                mark = MASTERY_ZH.get(m.state, m.state)
                why[v.key] = f"你自己标记为“{mark}”" + (f"：{m.note}" if m.note else "")
        elif m.state == "needs_review":
            why[v.key] = f"练习成绩偏低：{m.note}"
        elif m.state == "not_tested":
            why[v.key] = "还没有评分的练习，不知道掌握得怎样"
        elif m.state == "practicing":
            why[v.key] = f"还不稳：{m.note}"
        elif m.state == "seen":
            why[v.key] = "只接触过，还没有练习"
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
    kinds = {c["key"]: c["kind"] for c in row.concepts}
    if key not in kinds:
        raise NotFound("知识地图里没有这一项")
    if kinds[key] == "chapter":
        raise Invalid("掌握情况按节或知识点记，不按章")
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
        try:
            session.flush()
        except IntegrityError:
            raise Conflict("这一项刚被改过，请再试一次") from None
        view = _user_view(current)
        return audit.Outcome(current.id, view, {"code": row.code, "key": key, "state": new.state})

    entity = current.id if current is not None else None
    return audit.audited(session, actor, "concept_mastery", "set", entity, {}, op)


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
