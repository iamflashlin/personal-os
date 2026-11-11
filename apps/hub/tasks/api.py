# FastAPI reads parameter annotations at runtime; the routes below are built per Kind,
# so their body types are variables, which pyright cannot check statically.
# pyright: reportInvalidTypeForm=false
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.hub.tasks import service
from apps.hub.tasks.service import Actor, Kind
from packages.contracts.evidence import Evidence, TaskCompletion
from packages.contracts.tasks import Task

_STATUS = {service.NotFound: 404, service.Conflict: 409, service.Invalid: 422}
IDEMPOTENT_REPLAYED = "Idempotent-Replayed"


def _session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session


def _actor(request: Request) -> Actor:
    return Actor(owner_id=request.app.state.settings.owner_id)


SessionDep = Annotated[Session, Depends(_session)]
ActorDep = Annotated[Actor, Depends(_actor)]


def _call[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except service.TaskError as exc:
        raise HTTPException(status_code=_STATUS[type(exc)], detail=str(exc)) from exc


def _add_routes(router: APIRouter, kind: Kind) -> None:
    collection = f"/{kind.name}s"
    item = f"{collection}/{{entity_id}}"
    create_t, update_t, read_t = kind.create, kind.update, kind.read

    @router.post(collection, status_code=201, response_model=read_t, name=f"create_{kind.name}")
    def create(
        payload: create_t,
        response: Response,
        session: SessionDep,
        actor: ActorDep,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> BaseModel:
        created, replayed = _call(
            lambda: service.create(session, actor, kind, payload, idempotency_key)
        )
        if replayed:
            response.headers[IDEMPOTENT_REPLAYED] = "true"
        return created

    @router.get(collection, response_model=list[read_t], name=f"list_{kind.name}s")
    def list_all(session: SessionDep, actor: ActorDep) -> list[BaseModel]:
        return service.list_all(session, actor, kind)

    @router.get(item, response_model=read_t, name=f"get_{kind.name}")
    def get(entity_id: str, session: SessionDep, actor: ActorDep) -> BaseModel:
        return _call(lambda: service.get(session, actor, kind, entity_id))

    @router.patch(item, response_model=read_t, name=f"update_{kind.name}")
    def update(entity_id: str, patch: update_t, session: SessionDep, actor: ActorDep) -> BaseModel:
        return _call(lambda: service.update(session, actor, kind, entity_id, patch))

    @router.delete(item, status_code=204, name=f"delete_{kind.name}")
    def delete(entity_id: str, session: SessionDep, actor: ActorDep) -> None:
        _call(lambda: service.delete(session, actor, kind, entity_id))


def _add_completion_routes(router: APIRouter) -> None:
    @router.post("/tasks/{task_id}/complete", response_model=Task, name="complete_task")
    def complete(
        task_id: str, completion: TaskCompletion, session: SessionDep, actor: ActorDep
    ) -> Task:
        """Mark a task done. Records a `user_confirmation` Evidence row in the same write."""
        return _call(lambda: service.complete(session, actor, task_id, completion))

    @router.get(
        "/tasks/{task_id}/evidence", response_model=list[Evidence], name="list_task_evidence"
    )
    def list_evidence(task_id: str, session: SessionDep, actor: ActorDep) -> list[Evidence]:
        return _call(lambda: service.evidence_for(session, actor, task_id))


def build_router() -> APIRouter:
    router = APIRouter(tags=["tasks"])
    for kind in service.KINDS.values():
        _add_routes(router, kind)
    _add_completion_routes(router)
    return router
