from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from apps.hub.core.http import ActorDep, SessionDep, acall, call
from apps.hub.devices import service as devices
from apps.hub.study import service
from packages.contracts.study import StudyFinish, StudyPlan, StudySession, StudyStart

IDEMPOTENT_REPLAYED = "Idempotent-Replayed"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/study", tags=["study"])

    @router.get("/next", name="get_next_study_plan")
    def next_plan(session: SessionDep, actor: ActorDep) -> StudyPlan:
        return call(lambda: service.next_plan(session, actor))

    @router.get("/plans/{code}", name="get_study_plan")
    def plan(code: str, session: SessionDep, actor: ActorDep) -> StudyPlan:
        return call(lambda: service.plan(session, actor, code))

    @router.post("/sessions", status_code=201, name="start_study_session")
    async def start(
        body: StudyStart,
        request: Request,
        response: Response,
        actor: ActorDep,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=180)],
    ) -> StudySession:
        links: devices.AgentLinks = request.app.state.agent_links
        stored, replayed = await acall(
            service.start(request.app.state.engine, links, actor, body, idempotency_key)
        )
        if replayed:
            response.headers[IDEMPOTENT_REPLAYED] = "true"
        return stored

    @router.get("/sessions/{session_id}", name="get_study_session")
    def get(session_id: str, session: SessionDep, actor: ActorDep) -> StudySession:
        return call(lambda: service.get(session, actor, session_id))

    @router.post("/sessions/{session_id}/finish", name="finish_study_session")
    def finish(
        session_id: str, body: StudyFinish, session: SessionDep, actor: ActorDep
    ) -> StudySession:
        return call(lambda: service.finish(session, actor, session_id, body))

    return router
