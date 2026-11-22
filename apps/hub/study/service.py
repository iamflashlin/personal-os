# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation)
"""开始学习 (ADR 0042): what to study next, open it on the PC, remember the session.

The plan comes from the course map (academic): the nearest upcoming exam's review order,
weakest section first. Each step is a whitelisted `open_url`, dispatched through the
actions module, so the agent verifies every window and nothing runs twice per key.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.academic import service as academic
from apps.hub.actions import service as actions
from apps.hub.audit import service as audit
from apps.hub.core.db import run_in_session
from apps.hub.core.domain import Actor, Conflict, DomainError, Invalid, NotFound, Unavailable
from apps.hub.devices import service as devices
from apps.hub.study.models import StudySessionRow
from packages.contracts.actions import TITLE_MAX, ActionCreate, ActionName, OpenUrlParams
from packages.contracts.course_map import ConceptView, CourseMap, ExamView
from packages.contracts.study import (
    LastSession,
    NextUp,
    StepRun,
    StepStatus,
    StudyFinish,
    StudyPlan,
    StudySession,
    StudySessionStatus,
    StudyStart,
    StudyStep,
    step_status,
)

ENTITY = "study_session"
# A section finished this recently is not suggested again for the same course.
RECENT = timedelta(days=3)
_WEAK = {"needs_review": 0, "not_tested": 1, "seen": 2, "practicing": 3}
_WHY = {
    "needs_review": "练习成绩偏低",
    "not_tested": "还没有评分的练习，不知道掌握得怎样",
    "seen": "只接触过，还没有练习",
    "practicing": "还不稳",
}
_EXTENSION = re.compile(r"\.(pdf|pptx?|docx?|xlsx?)$", re.IGNORECASE)


def _title_hint(name: str) -> str:
    """The part of a file or page name a browser tab title will contain."""
    return _EXTENSION.sub("", name.strip())[:TITLE_MAX]


def _open(label: str, url: str, title: str) -> StudyStep | None:
    hint = _title_hint(title)
    if not url or not hint:
        return None
    try:
        params = OpenUrlParams.model_validate({"url": url, "expect_title_contains": hint})
    except ValidationError:
        return None  # not an http(s) link: never sent to the PC
    return StudyStep(label=label, action=ActionName.open_url, params=params.model_dump(mode="json"))


def _recent_keys(session: Session, actor: Actor, code: str, now: datetime) -> set[str]:
    rows = session.scalars(
        select(StudySessionRow).where(
            StudySessionRow.owner_id == actor.owner_id,
            StudySessionRow.course_code == code,
            StudySessionRow.status == StudySessionStatus.finished,
            StudySessionRow.finished_at >= now - RECENT,
        )
    ).all()
    return {str(r.next.get("key") or "") for r in rows} - {""}


def _upcoming(cm: CourseMap) -> ExamView | None:
    ahead = [e for e in cm.exams if e.days_left is not None and e.days_left >= 0]
    return min(ahead, key=lambda e: e.days_left or 0, default=None)


def _label(v: ConceptView) -> str:
    return f"{v.key} {v.title_zh or v.title}"


def _pick(
    session: Session, actor: Actor, cm: CourseMap, recent: set[str], now: datetime
) -> tuple[NextUp, ConceptView | None, ExamView | None]:
    exam = _upcoming(cm)
    if exam is not None:
        em = academic.exam_map(session, actor, cm.course_code, exam.name, now)
        views = {v.key: v for v in [*em.sections, *em.prerequisites]}
        order = [*em.suggested, *(v.key for v in em.sections)]
        key = next((k for k in order if k not in recent and k in views), None)
        days = f"{exam.name} 还有 {exam.days_left} 天"
        if key is None:
            why = f"考试范围都复习过一遍了（{days}），可以做复习题"
            return (
                NextUp(key="", title=f"做 {exam.name} 复习题", why=why, page=None, exam=exam.name),
                None,
                exam,
            )
        v = views[key]
        reason = em.why.get(key, "考试范围内，按教学顺序")
        title = f"复习 {_label(v)}"
        return (
            NextUp(key=key, title=title, why=f"{reason}（{days}）", page=v.page, exam=exam.name),
            v,
            exam,
        )
    sections = [c for c in cm.concepts if c.kind == "section" and c.key not in recent]

    def weakness(v: ConceptView) -> int:
        return _WEAK.get(v.mastery.state, 9) if v.mastery else 9

    weakest = min(sections, key=weakness, default=None)
    if weakest is None or weakness(weakest) == 9:
        return (
            NextUp(
                key="",
                title="看讲义",
                why="最近没有考试，各节也没有需要补的地方",
                page=None,
                exam="",
            ),
            None,
            None,
        )
    state = weakest.mastery.state if weakest.mastery else ""
    why = f"{_WHY[state]}（最近没有考试）"
    return (
        NextUp(
            key=weakest.key, title=f"巩固 {_label(weakest)}", why=why, page=weakest.page, exam=""
        ),
        weakest,
        None,
    )


def _last(session: Session, actor: Actor, code: str) -> LastSession | None:
    row = session.scalars(
        select(StudySessionRow)
        .where(StudySessionRow.owner_id == actor.owner_id, StudySessionRow.course_code == code)
        .order_by(StudySessionRow.created_at.desc(), StudySessionRow.id.desc())
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    return LastSession(
        started_at=row.created_at, finished_at=row.finished_at, title=str(row.next.get("title"))
    )


def plan(session: Session, actor: Actor, code: str, now: datetime | None = None) -> StudyPlan:
    now = now or datetime.now(UTC)
    cm = academic.course_map(session, actor, code, now)
    nxt, section, exam = _pick(
        session, actor, cm, _recent_keys(session, actor, cm.course_code, now), now
    )
    candidates: list[StudyStep | None] = []
    if section is not None:
        for r in section.resources[:1]:
            candidates.append(_open(f"打开 {section.key} 的老师资料", r.url, r.title))
        if section.material_url:
            page = f"（第 {section.page} 页）" if section.page else ""
            candidates.append(_open(f"打开讲义{page}", section.material_url, cm.material))
    if exam is not None and exam.review_url:
        candidates.append(_open(f"打开 {exam.name} 复习资料", exam.review_url, exam.review))
    if not any(candidates):  # nothing section-specific: at least the course notes
        url = next((c.material_url for c in cm.concepts if c.material_url), "")
        candidates.append(_open("打开讲义", url, cm.material))
    steps: list[StudyStep] = []
    seen: set[str] = set()
    for step in candidates:
        if step is not None and step.params["url"] not in seen:
            seen.add(step.params["url"])
            steps.append(step)
    return StudyPlan(
        course_code=cm.course_code,
        next=nxt,
        steps=steps,
        last=_last(session, actor, cm.course_code),
    )


def next_plan(session: Session, actor: Actor, now: datetime | None = None) -> StudyPlan:
    """The course to study now: the one with the nearest upcoming exam."""
    now = now or datetime.now(UTC)
    codes = academic.map_codes(session, actor)
    if not codes:
        raise NotFound("还没有课程地图")

    def soonest(code: str) -> int:
        exam = _upcoming(academic.course_map(session, actor, code, now))
        return exam.days_left if exam is not None and exam.days_left is not None else 10_000

    return plan(session, actor, min(codes, key=soonest), now)


def _row(session: Session, actor: Actor, session_id: str) -> StudySessionRow:
    row = session.get(StudySessionRow, session_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"study session {session_id} not found")
    return row


def step_key(session_key: str, index: int) -> str:
    """The action Idempotency-Key of one step, apart from keys sent to POST /actions."""
    return f"study:{session_key}:{index}"


def _read(session: Session, actor: Actor, row: StudySessionRow) -> StudySession:
    """Each step's state comes from its action run, found by its key: a run exists if and
    only if the step was stored for sending, so a half-finished start never shows a step
    that ran as not sent."""
    steps: list[StepRun] = []
    for i, s in enumerate(row.steps):
        run = actions.get_by_key(session, actor, step_key(row.idempotency_key, i))
        if run is None:
            steps.append(
                StepRun(
                    label=s["label"],
                    action_run_id=None,
                    status=StepStatus.not_sent,
                    message="电脑助手不在线，这一步没有发出去",
                )
            )
        else:
            steps.append(
                StepRun(
                    label=s["label"],
                    action_run_id=run.id,
                    status=step_status(run.status),
                    message=run.message,
                )
            )
    return StudySession(
        id=row.id,
        course_code=row.course_code,
        status=StudySessionStatus(row.status),
        next=NextUp.model_validate(row.next),
        steps=steps,
        started_at=row.created_at,
        finished_at=row.finished_at,
        note=row.note,
        version=row.version,
    )


def get(session: Session, actor: Actor, session_id: str) -> StudySession:
    return _read(session, actor, _row(session, actor, session_id))


@dataclass(frozen=True)
class _Started:
    session_id: str
    replayed: bool
    to_send: list[tuple[int, StudyStep]]  # steps without an action run yet


def _create(
    session: Session, actor: Actor, body: StudyStart, key: str, online: bool, now: datetime
) -> _Started:
    """The stored session for `key` (made now if new) and the steps still to send.

    A replay never makes a second session; its unsent steps are sent again (each step
    has its own key, so a step still runs at most once). A new key needs the agent.
    """
    seen = session.scalars(
        select(StudySessionRow).where(
            StudySessionRow.owner_id == actor.owner_id, StudySessionRow.idempotency_key == key
        )
    ).one_or_none()
    if seen is not None:
        if (
            seen.course_code
            != academic.course_map(session, actor, body.course_code, now).course_code
        ):
            raise Invalid("Idempotency-Key was already used for another course")
        todo = [
            (i, StudyStep.model_validate(s))
            for i, s in enumerate(seen.steps)
            if actions.get_by_key(session, actor, step_key(key, i)) is None
        ]
        open_steps = todo if online and seen.status == StudySessionStatus.started else []
        return _Started(seen.id, True, open_steps)
    if not online:
        raise Unavailable("电脑助手没有连上，没法替你打开")
    p = plan(session, actor, body.course_code, now)

    def op() -> audit.Outcome[StudySessionRow]:
        row = StudySessionRow(
            owner_id=actor.owner_id,
            source=actor.source,
            course_code=p.course_code,
            status=StudySessionStatus.started,
            next=p.next.model_dump(mode="json"),
            steps=[s.model_dump(mode="json") for s in p.steps],
            idempotency_key=key,
            note="",
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict("this start is already being handled") from exc
        return audit.Outcome(row.id, row, {"steps": len(p.steps)})

    detail = {"course_code": p.course_code, "next": p.next.title}
    row = audit.audited(session, actor, ENTITY, "start", None, detail, op)
    return _Started(row.id, False, list(enumerate(p.steps)))


async def start(
    engine: Engine,
    links: devices.AgentLinks,
    actor: Actor,
    body: StudyStart,
    key: str,
    now: datetime | None = None,
) -> tuple[StudySession, bool]:
    """Store the session, then send each step to the PC, at most once per step.

    Returns the session and whether this was a replay of `key`.
    """
    when = now or datetime.now(UTC)
    online = links.current(actor.owner_id) is not None
    started = await run_in_session(engine, lambda s: _create(s, actor, body, key, online, when))
    for i, step in started.to_send:
        try:
            await actions.dispatch(
                engine,
                links,
                actor,
                step_key(key, i),
                ActionCreate(name=step.action, params=step.params),
            )
        except DomainError:
            # The agent left (or refused this action): the step shows as not sent, and a
            # replay of the same key sends it again.
            continue
    stored = await run_in_session(engine, lambda s: get(s, actor, started.session_id))
    return stored, started.replayed


def finish(
    session: Session, actor: Actor, session_id: str, body: StudyFinish, now: datetime | None = None
) -> StudySession:
    def op() -> audit.Outcome[StudySessionRow]:
        row = _row(session, actor, session_id)
        if row.version != body.version:
            raise Conflict("这次学习已经被改过了，刷新后再试")
        if row.status == StudySessionStatus.finished:
            raise Conflict("这次学习已经结束了")
        row.status = StudySessionStatus.finished
        row.finished_at = now or datetime.now(UTC)
        row.note = body.note
        session.flush()
        return audit.Outcome(row.id, row)

    row = audit.audited(session, actor, ENTITY, "finish", session_id, {"note": body.note}, op)
    return _read(session, actor, row)
