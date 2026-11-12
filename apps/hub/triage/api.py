from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.hub.core import zones
from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.triage import service
from packages.contracts.triage import (
    HandledMark,
    HandleRequest,
    ItemHandled,
    RulePatch,
    TriageBatch,
    TriageRule,
    TriageView,
)


def _today(time_zone: str) -> datetime:
    try:
        zone = zones.zone_or_local(time_zone)
    except zones.UnknownZone:
        raise HTTPException(status_code=422, detail="unknown time zone") from None
    return datetime.now(UTC).astimezone(zone)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/triage", tags=["triage"])

    @router.get("", name="get_triage")
    def view(
        session: SessionDep,
        actor: ActorDep,
        time_zone: Annotated[str, Query(max_length=64)] = "",
    ) -> TriageView:
        return service.view(session, actor, _today(time_zone).date())

    @router.post("/handle", name="handle_mail")
    def handle(
        session: SessionDep,
        actor: ActorDep,
        body: HandleRequest,
        time_zone: Annotated[str, Query(max_length=64)] = "",
    ) -> TriageBatch:
        now = _today(time_zone)
        return call(lambda: service.handle(session, actor, body, now.date(), now.astimezone(UTC)))

    @router.post("/batches/{batch_id}/undo", name="undo_batch")
    def undo(session: SessionDep, actor: ActorDep, batch_id: str) -> TriageBatch:
        return call(lambda: service.undo(session, actor, batch_id, datetime.now(UTC)))

    @router.put("/items/{item_id}", name="set_mail_handled")
    def set_item(
        session: SessionDep, actor: ActorDep, item_id: str, body: ItemHandled
    ) -> HandledMark:
        return call(lambda: service.set_item(session, actor, item_id, body.handled))

    @router.patch("/rules/{rule_id}", name="set_rule")
    def set_rule(
        session: SessionDep,
        actor: ActorDep,
        rule_id: str,
        body: RulePatch,
        time_zone: Annotated[str, Query(max_length=64)] = "",
    ) -> TriageRule:
        today = _today(time_zone).date()
        return call(lambda: service.set_rule_enabled(session, actor, rule_id, body.enabled, today))

    return router
