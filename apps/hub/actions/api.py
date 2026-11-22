from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response

from apps.hub.actions import service
from apps.hub.core.http import ActorDep, SessionDep, acall, call
from apps.hub.devices import service as devices
from packages.contracts.actions import ActionCreate, ActionRun

IDEMPOTENT_REPLAYED = "Idempotent-Replayed"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/actions", tags=["actions"])

    @router.post("", status_code=202, name="create_action")
    async def create(
        payload: ActionCreate,
        request: Request,
        response: Response,
        actor: ActorDep,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> ActionRun:
        links: devices.AgentLinks = request.app.state.agent_links
        dispatch = await acall(
            service.dispatch(request.app.state.engine, links, actor, idempotency_key, payload)
        )
        if dispatch.request is None:
            response.headers[IDEMPOTENT_REPLAYED] = "true"
        return dispatch.run

    @router.get("", name="list_actions")
    def list_runs(
        session: SessionDep, actor: ActorDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[ActionRun]:
        return service.list_runs(session, actor, limit)

    @router.get("/{action_id}", name="get_action")
    def get(action_id: str, session: SessionDep, actor: ActorDep) -> ActionRun:
        return call(lambda: service.get(session, actor, action_id))

    return router
