from fastapi import APIRouter

from apps.hub.core.http import ActorDep, SessionDep
from apps.hub.gpa import service
from packages.contracts.gpa import GpaView


def build_router() -> APIRouter:
    router = APIRouter(prefix="/gpa", tags=["gpa"])

    @router.get("", name="get_gpa")
    def view(session: SessionDep, actor: ActorDep) -> GpaView:
        return service.view(session, actor)

    return router
