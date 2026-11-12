# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from apps.hub.chat import service
from apps.hub.core import zones
from apps.hub.core.http import ActorDep
from apps.hub.models import service as models
from packages.contracts.chat import ChatAnswer, ChatAsk


def build_router() -> APIRouter:
    router = APIRouter(prefix="/chat", tags=["chat"])

    # A plain `def`: FastAPI runs it in a worker thread, so a slow model call does not
    # block other requests.
    @router.post("/ask", name="ask_mail")
    def ask(request: Request, actor: ActorDep, body: ChatAsk) -> ChatAnswer:
        try:
            zone = zones.zone_or_local(body.time_zone)
        except zones.UnknownZone:
            raise HTTPException(status_code=422, detail="unknown time zone") from None
        state = request.app.state
        try:
            return service.ask(
                state.engine,
                state.secret_store,
                actor,
                state.model_provider,
                models.model_name(state.settings),
                models.budget_micro_usd(state.settings),
                body,
                datetime.now(UTC),
                zone,
            )
        except models.ModelUnavailable as exc:
            notice = service.NOTICES.get(exc.reason, "AI 现在用不了")
            raise HTTPException(
                status_code=503, detail=notice, headers={"X-Model-Unavailable": exc.reason}
            ) from None
        except models.ModelFailed as exc:
            detail = "AI 这次没答上来，请再问一次" if exc.retryable else "这个问题 AI 处理不了"
            raise HTTPException(status_code=502, detail=detail) from None

    return router
