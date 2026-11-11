from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from apps.hub.actions import service
from apps.hub.core.domain import Actor
from apps.hub.core.http import ActorDep, SessionDep, call, run_in_session
from apps.hub.devices import service as devices
from packages.contracts.actions import ActionCreate, ActionRun
from packages.contracts.agent_protocol import ActionRequestMsg

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
        engine = request.app.state.engine
        links: devices.AgentLinks = request.app.state.agent_links
        link = links.current(actor.owner_id)
        dispatch = await run_in_session(
            engine, lambda s: call(lambda: service.begin(s, actor, idempotency_key, payload, link))
        )
        if dispatch.request is None:
            response.headers[IDEMPOTENT_REPLAYED] = "true"
            return dispatch.run
        assert link is not None  # begin() refuses to dispatch without one
        run_id = dispatch.run.id
        link.in_flight.add(run_id)
        # No await since the add: if the link is still current, its disconnect handler has
        # not run yet and will see this run in in_flight.
        if links.current(actor.owner_id) is link:
            try:
                await link.send(ActionRequestMsg(request=dispatch.request))
                return dispatch.run
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
        link.in_flight.discard(run_id)
        return await run_in_session(engine, lambda s: _lost(s, actor, run_id))

    @router.get("", name="list_actions")
    def list_runs(
        session: SessionDep, actor: ActorDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[ActionRun]:
        return service.list_runs(session, actor, limit)

    @router.get("/{action_id}", name="get_action")
    def get(action_id: str, session: SessionDep, actor: ActorDep) -> ActionRun:
        return call(lambda: service.get(session, actor, action_id))

    return router


def _lost(session: Session, actor: Actor, run_id: str) -> ActionRun:
    service.mark_lost(session, actor, {run_id})
    return service.get(session, actor, run_id)
