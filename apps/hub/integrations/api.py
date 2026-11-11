from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.integrations import service
from packages.contracts.integrations import Integration, IntegrationCreate, SyncedItem


def build_router() -> APIRouter:
    router = APIRouter(prefix="/integrations", tags=["integrations"])

    @router.post("", status_code=201, name="create_integration")
    def create(payload: IntegrationCreate, session: SessionDep, actor: ActorDep) -> Integration:
        return call(lambda: service.create(session, actor, payload, datetime.now(UTC)))

    @router.get("", name="list_integrations")
    def list_all(session: SessionDep, actor: ActorDep) -> list[Integration]:
        return service.list_all(session, actor)

    @router.get("/{integration_id}", name="get_integration")
    def get(integration_id: str, session: SessionDep, actor: ActorDep) -> Integration:
        return call(lambda: service.get(session, actor, integration_id))

    @router.delete("/{integration_id}", status_code=204, name="delete_integration")
    def delete(integration_id: str, session: SessionDep, actor: ActorDep) -> None:
        call(lambda: service.delete(session, actor, integration_id))

    @router.post("/{integration_id}/sync", status_code=202, name="sync_integration")
    def sync(integration_id: str, session: SessionDep, actor: ActorDep) -> dict[str, str]:
        job_id = call(
            lambda: service.request_sync(session, actor, integration_id, datetime.now(UTC))
        )
        return {"job_id": job_id}

    @router.get("/{integration_id}/items", name="list_integration_items")
    def items(
        integration_id: str,
        session: SessionDep,
        actor: ActorDep,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[SyncedItem]:
        return call(lambda: service.items(session, actor, integration_id, start, end, limit))

    return router
