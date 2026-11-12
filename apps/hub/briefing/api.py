from datetime import UTC, datetime, tzinfo
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from apps.hub.briefing import service
from apps.hub.core import zones
from apps.hub.core.http import ActorDep, SessionDep
from apps.hub.models import service as models
from apps.hub.summaries import service as summaries
from packages.contracts.today import TodayView


def _zone(name: str) -> tzinfo:
    try:
        return zones.zone_or_local(name)
    except zones.UnknownZone:
        raise HTTPException(status_code=422, detail=f"unknown time zone {name!r}") from None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/today", tags=["today"])

    @router.get("", name="get_today")
    def today(
        request: Request,
        session: SessionDep,
        actor: ActorDep,
        tz: Annotated[str, Query(max_length=64, description="IANA zone; default: this PC's")] = "",
    ) -> TodayView:
        now = datetime.now(UTC)
        settings = request.app.state.settings
        ai = summaries.status(
            session,
            actor,
            now,
            models.budget_micro_usd(settings),
            request.app.state.model_provider.vendor,
            models.model_name(settings),
        )
        notice = ai.notice if ai.pending else ""  # no banner while no mail is waiting
        return service.today(session, actor, now, _zone(tz), ai_notice=notice)

    return router
