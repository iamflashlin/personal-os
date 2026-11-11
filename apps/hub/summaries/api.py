from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from apps.hub.core.http import ActorDep, SessionDep
from apps.hub.models import service as models
from apps.hub.summaries import service
from packages.contracts.summaries import EmailSummary, RunStarted, SummariesStatus


def build_router() -> APIRouter:
    router = APIRouter(prefix="/summaries", tags=["summaries"])

    @router.get("/email", name="email_summaries")
    def email(
        session: SessionDep,
        actor: ActorDep,
        item_ids: Annotated[str, Query(max_length=6000)] = "",
    ) -> list[EmailSummary]:
        ids = [i for i in item_ids.split(",") if i][: service.MAX_ITEM_IDS]
        return service.summaries_for(session, actor, ids)

    @router.get("/status", name="summaries_status")
    def status(request: Request, session: SessionDep, actor: ActorDep) -> SummariesStatus:
        settings = request.app.state.settings
        return service.status(
            session,
            actor,
            datetime.now(UTC),
            models.budget_micro_usd(settings),
            request.app.state.model_provider.vendor,
            models.model_name(settings),
        )

    @router.post("/run", status_code=202, name="run_summaries")
    def run(session: SessionDep, actor: ActorDep) -> RunStarted:
        return RunStarted(job_id=service.request_run(session, actor, datetime.now(UTC)))

    return router
