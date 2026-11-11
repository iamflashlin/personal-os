from datetime import UTC, datetime, tzinfo
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from apps.hub.briefing import service
from apps.hub.core.http import ActorDep, SessionDep
from packages.contracts.today import TodayView


def _zone(name: str) -> tzinfo:
    if not name:
        local = datetime.now().astimezone().tzinfo
        return local or UTC
    try:
        return ZoneInfo(name)
    # A key like "America" names a tzdata folder and raises an OSError, not NotFound.
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise HTTPException(status_code=422, detail=f"unknown time zone {name!r}") from None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/today", tags=["today"])

    @router.get("", name="get_today")
    def today(
        session: SessionDep,
        actor: ActorDep,
        tz: Annotated[str, Query(max_length=64, description="IANA zone; default: this PC's")] = "",
    ) -> TodayView:
        return service.today(session, actor, datetime.now(UTC), _zone(tz))

    return router
