from typing import Annotated

from fastapi import APIRouter, Query

from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.memory import service
from packages.contracts.memory import (
    Memory,
    MemoryConfirm,
    MemoryCreate,
    MemoryHit,
    MemoryUpdate,
)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/memories", tags=["memory"])

    @router.post("", status_code=201, name="create_memory")
    def create(payload: MemoryCreate, session: SessionDep, actor: ActorDep) -> Memory:
        return call(lambda: service.create(session, actor, payload))

    @router.get("", name="list_memories")
    def list_all(
        session: SessionDep, actor: ActorDep, include_expired: bool = False
    ) -> list[Memory]:
        return service.list_all(session, actor, include_expired)

    # Declared before "/{memory_id}" so "search" is not taken for an id.
    @router.get("/search", name="search_memories")
    def search(
        session: SessionDep,
        actor: ActorDep,
        q: Annotated[str, Query(min_length=1, max_length=500)],
        include_expired: bool = False,
        include_secret: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[MemoryHit]:
        return call(
            lambda: service.search(
                session,
                actor,
                q,
                include_expired=include_expired,
                include_secret=include_secret,
                limit=limit,
            )
        )

    @router.get("/{memory_id}", name="get_memory")
    def get(memory_id: str, session: SessionDep, actor: ActorDep) -> Memory:
        return call(lambda: service.get(session, actor, memory_id))

    @router.patch("/{memory_id}", name="update_memory")
    def update(memory_id: str, patch: MemoryUpdate, session: SessionDep, actor: ActorDep) -> Memory:
        return call(lambda: service.update(session, actor, memory_id, patch))

    @router.post("/{memory_id}/confirm", name="confirm_memory")
    def confirm(
        memory_id: str, request: MemoryConfirm, session: SessionDep, actor: ActorDep
    ) -> Memory:
        return call(lambda: service.confirm(session, actor, memory_id, request))

    @router.delete("/{memory_id}", status_code=204, name="delete_memory")
    def delete(memory_id: str, session: SessionDep, actor: ActorDep) -> None:
        call(lambda: service.delete(session, actor, memory_id))

    return router
