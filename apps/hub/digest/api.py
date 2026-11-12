from datetime import UTC, datetime, tzinfo
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from apps.hub.core import zones
from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.digest import service
from packages.contracts.digest import Channel, DigestItem, DigestView, NewDigestItem, ReadMark

ZoneQuery = Annotated[str, Query(max_length=64)]


def _zone(name: str) -> tzinfo:
    try:
        return zones.zone_or_local(name)
    except zones.UnknownZone:
        raise HTTPException(status_code=422, detail="unknown time zone") from None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/digest", tags=["digest"])

    @router.get("", name="get_digest")
    def view(
        session: SessionDep,
        actor: ActorDep,
        which: Annotated[Literal["today", "history"], Query(alias="view")] = "today",
        unread_only: bool = False,
        channel: Channel | None = None,
        time_zone: ZoneQuery = "",
    ) -> DigestView:
        zone = _zone(time_zone)
        return service.view(session, actor, which, datetime.now(UTC), zone, unread_only, channel)

    @router.post("/items", status_code=201, name="add_digest_item")
    def add(session: SessionDep, actor: ActorDep, body: NewDigestItem) -> DigestItem:
        return call(lambda: service.add(session, actor, body, datetime.now(UTC)))

    @router.put("/items/{item_id}/read", name="mark_digest_read")
    def mark(session: SessionDep, actor: ActorDep, item_id: str, body: ReadMark) -> DigestItem:
        return call(lambda: service.set_read(session, actor, item_id, body.read, datetime.now(UTC)))

    @router.post("/read-all", name="digest_read_all")
    def read_all(
        session: SessionDep,
        actor: ActorDep,
        which: Annotated[Literal["today", "history"], Query(alias="view")] = "today",
        channel: Channel | None = None,
        time_zone: ZoneQuery = "",
    ) -> dict[str, int]:
        zone = _zone(time_zone)
        marked = service.read_all(session, actor, which, datetime.now(UTC), zone, channel)
        return {"marked": marked}

    return router
