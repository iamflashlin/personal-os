# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Course profiles (ADR 0040): the syllabus rules the grade engine follows.

Profiles are written by an import (from the syllabi, with each rule's source) or by the
user, and the user confirms each one once. Changing a confirmed profile's content clears
the confirmation, so a silent change never passes as checked."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.academic.models import CourseProfileRow
from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, NotFound
from packages.contracts.academic import CourseProfile, ProfileFields

_CONTENT = (
    "title",
    "term",
    "units",
    "units_source",
    "scale",
    "scale_source",
    "categories",
    "rules",
    "open_questions",
    "syllabus_source",
)


def _read(row: CourseProfileRow) -> CourseProfile:
    return CourseProfile(
        id=row.id,
        code=row.code,
        title=row.title,
        term=row.term,
        units=row.units,
        units_source=row.units_source,
        scale=row.scale,
        scale_source=row.scale_source,
        categories=row.categories,
        rules=row.rules,
        open_questions=row.open_questions,
        syllabus_source=row.syllabus_source,
        confirmed_at=row.confirmed_at,
        origin=row.source,
        updated_at=row.updated_at,
        version=row.version,
    )


def _content(f: ProfileFields) -> dict[str, object]:
    dumped = f.model_dump(mode="json")
    return {k: dumped[k] for k in _CONTENT}


def _row(session: Session, actor: Actor, code: str) -> CourseProfileRow | None:
    return session.scalar(
        select(CourseProfileRow).where(
            CourseProfileRow.owner_id == actor.owner_id, CourseProfileRow.code == code
        )
    )


def profiles(session: Session, actor: Actor) -> list[CourseProfile]:
    rows = session.scalars(
        select(CourseProfileRow)
        .where(CourseProfileRow.owner_id == actor.owner_id)
        .order_by(CourseProfileRow.code)
    )
    return [_read(r) for r in rows]


def profile(session: Session, actor: Actor, code: str) -> CourseProfile:
    row = _row(session, actor, code)
    if row is None:
        raise NotFound("这门课还没有规则卡")
    return _read(row)


def put(
    session: Session,
    actor: Actor,
    fields: ProfileFields,
    version: int | None,
    origin: str = "manual",
) -> CourseProfile:
    """Create (version None) or replace a course's profile."""
    row = _row(session, actor, fields.code)
    content = _content(fields)
    if row is None:
        if version is not None:
            raise NotFound("这门课还没有规则卡")

        def create() -> audit.Outcome[CourseProfile]:
            new = CourseProfileRow(
                owner_id=actor.owner_id, source=origin, version=1, code=fields.code, **content
            )
            session.add(new)
            try:
                session.flush()
            except IntegrityError:
                raise Conflict("这门课的规则卡刚被建好了，请刷新") from None
            return audit.Outcome(new.id, _read(new), {"code": fields.code})

        return audit.audited(session, actor, "course_profile", "create", None, {}, create)
    if version is None or row.version != version:
        raise Conflict("规则卡刚被改过，请刷新后再改")

    def update() -> audit.Outcome[CourseProfile]:
        changed = any(getattr(row, k) != v for k, v in content.items())
        for k, v in content.items():
            setattr(row, k, v)
        if changed:
            row.confirmed_at = None  # a changed profile needs the user's check again
            row.source = origin
        session.flush()
        return audit.Outcome(row.id, _read(row), {"code": row.code, "changed": changed})

    return audit.audited(session, actor, "course_profile", "update", row.id, {}, update)


def confirm(
    session: Session, actor: Actor, code: str, version: int, now: datetime
) -> CourseProfile:
    row = _row(session, actor, code)
    if row is None:
        raise NotFound("这门课还没有规则卡")
    if row.version != version:
        raise Conflict("规则卡刚被改过，请刷新后再确认")

    def op() -> audit.Outcome[CourseProfile]:
        row.confirmed_at = now
        session.flush()
        return audit.Outcome(row.id, _read(row), {"code": row.code})

    return audit.audited(session, actor, "course_profile", "confirm", row.id, {}, op)


__all__ = ["confirm", "profile", "profiles", "put"]
