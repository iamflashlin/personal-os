from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from apps.hub.core.http import ActorDep, SessionDep, acall, call
from apps.hub.devices import service as devices
from apps.hub.homework import service
from packages.contracts.homework import HomeworkBoard, HomeworkCheck, HomeworkOpened

IDEMPOTENT_REPLAYED = "Idempotent-Replayed"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/homework", tags=["homework"])

    @router.get("", name="get_homework_board")
    def board(session: SessionDep, actor: ActorDep) -> HomeworkBoard:
        return call(lambda: service.board(session, actor))

    @router.post("/check", status_code=202, name="check_homework")
    def check(session: SessionDep, actor: ActorDep) -> HomeworkCheck:
        return call(lambda: service.check(session, actor))

    @router.post("/{item_id}/open", status_code=202, name="open_homework")
    async def open_page(
        item_id: str,
        request: Request,
        response: Response,
        actor: ActorDep,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=180)],
    ) -> HomeworkOpened:
        links: devices.AgentLinks = request.app.state.agent_links
        opened = await acall(
            service.open_page(request.app.state.engine, links, actor, item_id, idempotency_key)
        )
        if opened.replayed:
            response.headers[IDEMPOTENT_REPLAYED] = "true"
        return opened

    return router
