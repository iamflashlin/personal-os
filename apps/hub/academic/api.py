from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from apps.hub.academic import service
from apps.hub.core.http import ActorDep, SessionDep, call
from packages.contracts.academic import CourseProfile, ProfileConfirm, ProfileWrite


def build_router() -> APIRouter:
    router = APIRouter(prefix="/academic", tags=["academic"])

    @router.get("/profiles", name="list_course_profiles")
    def list_profiles(session: SessionDep, actor: ActorDep) -> list[CourseProfile]:
        return service.profiles(session, actor)

    @router.get("/profiles/{code}", name="get_course_profile")
    def get_profile(session: SessionDep, actor: ActorDep, code: str) -> CourseProfile:
        return call(lambda: service.profile(session, actor, code))

    @router.put("/profiles/{code}", name="put_course_profile")
    def put_profile(
        session: SessionDep, actor: ActorDep, code: str, body: ProfileWrite
    ) -> CourseProfile:
        if body.fields.code != code:
            raise HTTPException(status_code=422, detail="the code in the path and body differ")
        return call(
            lambda: service.put(session, actor, body.fields, body.version, origin=actor.name)
        )

    @router.post("/profiles/{code}/confirm", name="confirm_course_profile")
    def confirm_profile(
        session: SessionDep, actor: ActorDep, code: str, body: ProfileConfirm
    ) -> CourseProfile:
        return call(lambda: service.confirm(session, actor, code, body.version, datetime.now(UTC)))

    return router
