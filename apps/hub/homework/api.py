from datetime import tzinfo
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from apps.hub.core import zones
from apps.hub.core.http import ActorDep, SessionDep, acall, call
from apps.hub.devices import service as devices
from apps.hub.homework import service
from packages.contracts.homework import (
    HomeworkBoard,
    HomeworkCheck,
    HomeworkOpened,
    HomeworkPlan,
    HomeworkSlot,
    HomeworkWeeks,
    PlannedTime,
)

IDEMPOTENT_REPLAYED = "Idempotent-Replayed"
ZoneQuery = Annotated[str, Query(max_length=64)]


def _zone(name: str) -> tzinfo:
    try:
        return zones.zone_or_local(name)
    except zones.UnknownZone:
        raise HTTPException(status_code=422, detail="unknown time zone") from None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/homework", tags=["homework"])

    @router.get("", name="get_homework_board")
    def board(session: SessionDep, actor: ActorDep) -> HomeworkBoard:
        return call(lambda: service.board(session, actor))

    @router.get("/weeks", name="get_homework_weeks")
    def weeks(
        session: SessionDep,
        actor: ActorDep,
        count: Annotated[int, Query(ge=1, le=12)] = 4,
        time_zone: ZoneQuery = "",
    ) -> HomeworkWeeks:
        zone = _zone(time_zone)
        return call(lambda: service.weeks(session, actor, count, zone))

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

    @router.get("/{item_id}/slot", name="suggest_homework_slot")
    def slot(
        item_id: str,
        session: SessionDep,
        actor: ActorDep,
        minutes: Annotated[int, Query(ge=30, le=480)] = 60,
        time_zone: ZoneQuery = "",
    ) -> HomeworkSlot:
        zone = _zone(time_zone)
        return call(lambda: service.suggest(session, actor, item_id, minutes, zone, time_zone))

    @router.post("/{item_id}/plan", status_code=201, name="plan_homework")
    def plan(
        item_id: str,
        body: HomeworkPlan,
        response: Response,
        session: SessionDep,
        actor: ActorDep,
        time_zone: ZoneQuery = "",
    ) -> PlannedTime:
        _zone(time_zone)
        planned, created = call(lambda: service.plan(session, actor, item_id, body, time_zone))
        if not created:
            response.status_code = 200  # already on the schedule: the block that is there
        return planned

    return router
