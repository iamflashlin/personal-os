from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from apps.hub.academic import maps, service
from apps.hub.core.http import ActorDep, SessionDep, call
from packages.contracts.academic import CourseProfile, ProfileConfirm, ProfileWrite, normal_code
from packages.contracts.course_map import CourseMap, ExamMap, MapIn, MasteryView, MasteryWrite


def build_router() -> APIRouter:
    router = APIRouter(prefix="/academic", tags=["academic"])

    @router.get("/profiles", name="list_course_profiles")
    def list_profiles(session: SessionDep, actor: ActorDep) -> list[CourseProfile]:
        return service.profiles(session, actor)

    @router.get("/profiles/{code}", name="get_course_profile")
    def get_profile(session: SessionDep, actor: ActorDep, code: str) -> CourseProfile:
        return call(lambda: service.profile(session, actor, normal_code(code)))

    @router.put("/profiles/{code}", name="put_course_profile")
    def put_profile(
        session: SessionDep, actor: ActorDep, code: str, body: ProfileWrite
    ) -> CourseProfile:
        if body.fields.code != normal_code(code):
            raise HTTPException(status_code=422, detail="the code in the path and body differ")
        return call(
            lambda: service.put(session, actor, body.fields, body.version, origin=actor.name)
        )

    @router.post("/profiles/{code}/confirm", name="confirm_course_profile")
    def confirm_profile(
        session: SessionDep, actor: ActorDep, code: str, body: ProfileConfirm
    ) -> CourseProfile:
        return call(
            lambda: service.confirm(
                session, actor, normal_code(code), body.version, datetime.now(UTC)
            )
        )

    @router.get("/maps", name="list_course_maps")
    def list_maps(session: SessionDep, actor: ActorDep) -> list[str]:
        return maps.map_codes(session, actor)

    @router.put("/maps/{code}", name="put_course_map")
    def put_map(session: SessionDep, actor: ActorDep, code: str, body: MapIn) -> dict[str, int]:
        if normal_code(body.course_code) != normal_code(code):
            raise HTTPException(status_code=422, detail="the code in the path and body differ")
        return {"version": call(lambda: maps.put_map(session, actor, body, origin=actor.name))}

    @router.get("/maps/{code}", name="get_course_map")
    def get_map(session: SessionDep, actor: ActorDep, code: str) -> CourseMap:
        return call(lambda: maps.course_map(session, actor, code))

    @router.get("/maps/{code}/exams/{name}", name="get_exam_map")
    def get_exam(session: SessionDep, actor: ActorDep, code: str, name: str) -> ExamMap:
        return call(lambda: maps.exam_map(session, actor, code, name))

    @router.put("/maps/{code}/mastery/{key}", name="set_concept_mastery")
    def set_mastery(
        session: SessionDep, actor: ActorDep, code: str, key: str, body: MasteryWrite
    ) -> MasteryView:
        return call(lambda: maps.set_mastery(session, actor, code, key, body, datetime.now(UTC)))

    @router.delete("/maps/{code}/mastery/{key}", status_code=204, name="clear_concept_mastery")
    def clear_mastery(session: SessionDep, actor: ActorDep, code: str, key: str) -> None:
        call(lambda: maps.clear_mastery(session, actor, code, key))

    return router
