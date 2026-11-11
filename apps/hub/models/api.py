from datetime import UTC, datetime

from fastapi import APIRouter, Request

from apps.hub.core.http import ActorDep, SessionDep
from apps.hub.models import service
from packages.contracts.models import ModelUsage


def build_router() -> APIRouter:
    router = APIRouter(prefix="/models", tags=["models"])

    @router.get("/usage", name="model_usage")
    def usage(request: Request, session: SessionDep, actor: ActorDep) -> ModelUsage:
        settings = request.app.state.settings
        provider = request.app.state.model_provider
        return service.usage(
            session,
            actor,
            datetime.now(UTC),
            service.budget_micro_usd(settings),
            provider.vendor,
            service.model_name(settings),
        )

    return router
