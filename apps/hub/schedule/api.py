from datetime import datetime, tzinfo
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.hub.core import zones
from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.schedule import service
from packages.contracts.schedule import Agenda, EventPatch, NewEvent, ScheduleEvent

ZoneQuery = Annotated[str, Query(max_length=64)]


def _zone(name: str) -> tzinfo:
    try:
        return zones.zone_or_local(name)
    except zones.UnknownZone:
        raise HTTPException(status_code=422, detail="unknown time zone") from None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/schedule", tags=["schedule"])

    @router.get("", name="get_agenda")
    def agenda(
        session: SessionDep,
        actor: ActorDep,
        start: datetime,
        end: datetime,
        time_zone: ZoneQuery = "",
    ) -> Agenda:
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(status_code=422, detail="start and end need a time zone offset")
        zone = _zone(time_zone)
        return call(lambda: service.agenda(session, actor, start, end, zone, time_zone))

    @router.post("/events", status_code=201, name="create_event")
    def create(
        session: SessionDep, actor: ActorDep, body: NewEvent, time_zone: ZoneQuery = ""
    ) -> ScheduleEvent:
        _zone(time_zone)
        return call(lambda: service.create(session, actor, body, time_zone))

    @router.put("/events/{event_id}", name="update_event")
    def update(
        session: SessionDep,
        actor: ActorDep,
        event_id: str,
        body: EventPatch,
        time_zone: ZoneQuery = "",
    ) -> ScheduleEvent:
        _zone(time_zone)
        return call(lambda: service.update(session, actor, event_id, body, time_zone))

    @router.delete("/events/{event_id}", status_code=204, name="delete_event")
    def delete(session: SessionDep, actor: ActorDep, event_id: str) -> None:
        call(lambda: service.delete(session, actor, event_id))

    return router
