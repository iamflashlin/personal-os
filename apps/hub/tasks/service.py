"""CRUD for goals, projects, tasks and workspaces.

Every write attempt that reaches this module is recorded in the audit log exactly once:
in the same transaction as the change when it succeeds, or on its own after a rollback
when it is rejected or fails.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.evidence import service as evidence
from apps.hub.tasks.models import GoalRow, IdempotencyKeyRow, ProjectRow, TaskRow, WorkspaceRow
from packages.contracts.evidence import Evidence, TaskCompletion
from packages.contracts.tasks import (
    CIS_COURSE_TAG,
    ExecutionMode,
    Goal,
    GoalCreate,
    GoalUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    Workspace,
    WorkspaceCreate,
    WorkspaceUpdate,
)

Rules = Callable[[dict[str, Any], Any], None]


def _no_rules(_data: dict[str, Any], _previous: Any) -> None:
    return None


def _task_rules(data: dict[str, Any], previous: TaskRow | None) -> None:
    becoming_done = data["status"] == TaskStatus.done and (
        previous is None or previous.status != TaskStatus.done
    )
    if becoming_done:
        raise Conflict("a task can be marked done only via POST /tasks/{id}/complete")
    leaving_done = previous is not None and previous.status == TaskStatus.done
    if leaving_done and data["status"] != TaskStatus.done:
        raise Conflict("a done task cannot be reopened; its Evidence stays with it")
    if data["execution_mode"] is None:
        cis = CIS_COURSE_TAG in data["tags"]
        data["execution_mode"] = ExecutionMode.human_led if cis else ExecutionMode.collaborate
    data["depends_on"] = list(dict.fromkeys(data["depends_on"]))
    if previous is not None and previous.id in data["depends_on"]:
        raise Invalid("a task cannot depend on itself")


@dataclass(frozen=True)
class Kind:
    name: str
    row: type[Any]
    create: type[BaseModel]
    update: type[BaseModel]
    read: type[BaseModel]
    refs: Mapping[str, type[Any]] = field(default_factory=dict[str, type[Any]])
    list_refs: Mapping[str, type[Any]] = field(default_factory=dict[str, type[Any]])
    rules: Rules = _no_rules


KINDS: dict[str, Kind] = {
    k.name: k
    for k in (
        Kind("goal", GoalRow, GoalCreate, GoalUpdate, Goal),
        Kind("project", ProjectRow, ProjectCreate, ProjectUpdate, Project, {"goal_id": GoalRow}),
        Kind(
            "task",
            TaskRow,
            TaskCreate,
            TaskUpdate,
            Task,
            refs={"project_id": ProjectRow},
            list_refs={"depends_on": TaskRow},
            rules=_task_rules,
        ),
        Kind(
            "workspace",
            WorkspaceRow,
            WorkspaceCreate,
            WorkspaceUpdate,
            Workspace,
            refs={"project_id": ProjectRow, "task_id": TaskRow},
        ),
    )
}


def _find(session: Session, actor: Actor, row_type: type[Any], entity_id: str) -> Any:
    row = session.get(row_type, entity_id)
    if row is None or row.owner_id != actor.owner_id:
        return None
    return row


def _get_row(session: Session, actor: Actor, kind: Kind, entity_id: str) -> Any:
    row = _find(session, actor, kind.row, entity_id)
    if row is None:
        raise NotFound(f"{kind.name} {entity_id} not found")
    return row


def _check_refs(session: Session, actor: Actor, kind: Kind, data: dict[str, Any]) -> None:
    for name, row_type in kind.refs.items():
        if data[name] is not None and _find(session, actor, row_type, data[name]) is None:
            raise Invalid(f"{name} {data[name]} does not exist")
    for name, row_type in kind.list_refs.items():
        for ref in data[name]:
            if _find(session, actor, row_type, ref) is None:
                raise Invalid(f"{name} entry {ref} does not exist")


def _read(kind: Kind, row: Any) -> BaseModel:
    return kind.read.model_validate(row, from_attributes=True)


def _request_hash(payload: BaseModel) -> str:
    """SHA-256 of the validated body, so omitted defaults and key order do not matter."""
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create(
    session: Session,
    actor: Actor,
    kind: Kind,
    payload: BaseModel,
    idempotency_key: str | None = None,
) -> tuple[BaseModel, bool]:
    """Return the created resource and whether it is a replay of an earlier request."""
    request_hash = _request_hash(payload)

    def op() -> audit.Outcome[tuple[BaseModel, bool]]:
        if idempotency_key is not None:
            seen = session.scalars(
                select(IdempotencyKeyRow).where(
                    IdempotencyKeyRow.owner_id == actor.owner_id,
                    IdempotencyKeyRow.key == idempotency_key,
                )
            ).one_or_none()
            if seen is not None:
                if seen.scope != kind.name:
                    raise Invalid("Idempotency-Key was already used for a different request")
                if seen.request_hash != request_hash:
                    raise Invalid("Idempotency-Key was already used with a different body")
                original = get(session, actor, kind, seen.entity_id)
                return audit.Outcome(seen.entity_id, (original, True), result="replayed")

        data = payload.model_dump()
        kind.rules(data, None)
        _check_refs(session, actor, kind, data)
        row = kind.row(owner_id=actor.owner_id, source=actor.source, **data)
        session.add(row)
        session.flush()
        if idempotency_key is not None:
            session.add(
                IdempotencyKeyRow(
                    owner_id=actor.owner_id,
                    source=actor.source,
                    key=idempotency_key,
                    scope=kind.name,
                    request_hash=request_hash,
                    entity_id=row.id,
                )
            )
            try:
                session.flush()
            except IntegrityError as exc:
                raise Conflict("Idempotency-Key is being used by a concurrent request") from exc
        stored = _read(kind, row)
        return audit.Outcome(row.id, (stored, False), {"stored": stored.model_dump(mode="json")})

    detail = {"payload": payload.model_dump(mode="json")}
    return audit.audited(session, actor, kind.name, "create", None, detail, op)


def get(session: Session, actor: Actor, kind: Kind, entity_id: str) -> BaseModel:
    return _read(kind, _get_row(session, actor, kind, entity_id))


def list_all(session: Session, actor: Actor, kind: Kind) -> list[BaseModel]:
    rows = session.scalars(
        select(kind.row)
        .where(kind.row.owner_id == actor.owner_id)
        .order_by(kind.row.created_at, kind.row.id)
    ).all()
    return [_read(kind, r) for r in rows]


def update(
    session: Session, actor: Actor, kind: Kind, entity_id: str, patch: BaseModel
) -> BaseModel:
    changes = patch.model_dump(exclude_unset=True, exclude={"version"})
    expected_version: int = getattr(patch, "version")  # noqa: B009  (every Update has it)

    def op() -> audit.Outcome[BaseModel]:
        row = _get_row(session, actor, kind, entity_id)
        if row.version != expected_version:
            raise Conflict(f"version is {row.version}, request was based on {expected_version}")
        current = kind.create.model_validate(row, from_attributes=True).model_dump()
        try:
            merged = kind.create.model_validate({**current, **changes}).model_dump()
        except ValidationError as exc:
            raise Invalid(str(exc)) from exc
        kind.rules(merged, row)
        _check_refs(session, actor, kind, merged)
        for name, value in merged.items():
            setattr(row, name, value)
        session.flush()
        return audit.Outcome(row.id, _read(kind, row))

    detail = {"changes": patch.model_dump(mode="json", exclude_unset=True)}
    return audit.audited(session, actor, kind.name, "update", entity_id, detail, op)


def delete(session: Session, actor: Actor, kind: Kind, entity_id: str) -> None:
    def op() -> audit.Outcome[None]:
        row = _get_row(session, actor, kind, entity_id)
        if kind.row is TaskRow:
            tasks = session.scalars(select(TaskRow).where(TaskRow.owner_id == actor.owner_id))
            for other in tasks:
                if entity_id in other.depends_on:
                    raise Conflict(f"task {other.id} depends on this task")
        session.delete(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict(f"{kind.name} {entity_id} is still referenced") from exc
        return audit.Outcome(entity_id, None)

    audit.audited(session, actor, kind.name, "delete", entity_id, {}, op)


def complete(session: Session, actor: Actor, task_id: str, completion: TaskCompletion) -> Task:
    """Mark a task done with a user-confirmation Evidence row, in one transaction.

    This is the only way to reach `done`; PATCH still refuses it (CLAUDE.md, ADR 0011).
    """
    kind = KINDS["task"]

    def op() -> audit.Outcome[Task]:
        row = _get_row(session, actor, kind, task_id)
        if row.version != completion.version:
            raise Conflict(f"version is {row.version}, request was based on {completion.version}")
        if row.status == TaskStatus.done:
            raise Conflict(f"task {task_id} is already done")
        proof = evidence.record_user_confirmation(
            session,
            owner_id=actor.owner_id,
            source=actor.source,
            task_id=task_id,
            note=completion.note,
        )
        row.status = TaskStatus.done
        session.flush()
        done = Task.model_validate(row, from_attributes=True)
        return audit.Outcome(task_id, done, {"evidence_id": proof.id, "kind": proof.kind})

    detail = {"request": completion.model_dump(mode="json")}
    return audit.audited(session, actor, kind.name, "complete", task_id, detail, op)


def evidence_for(session: Session, actor: Actor, task_id: str) -> list[Evidence]:
    _get_row(session, actor, KINDS["task"], task_id)
    return evidence.list_for_task(session, actor.owner_id, task_id)
