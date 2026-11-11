from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from apps.hub.core.http import ActorDep, SessionDep, call
from apps.hub.jobs import service
from packages.contracts.jobs import Job, JobStatus, Schedule


def build_router() -> APIRouter:
    """Read and retry only: jobs are created by Hub modules, never by HTTP clients."""
    router = APIRouter(prefix="/jobs", tags=["jobs"])

    @router.get("", name="list_jobs")
    def list_jobs(
        session: SessionDep,
        actor: ActorDep,
        status: JobStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[Job]:
        return service.list_jobs(session, actor, status, limit)

    # Declared before "/{job_id}" so "schedules" is not taken for an id.
    @router.get("/schedules", name="list_job_schedules")
    def list_schedules(session: SessionDep, actor: ActorDep) -> list[Schedule]:
        return service.list_schedules(session, actor)

    @router.get("/{job_id}", name="get_job")
    def get(job_id: str, session: SessionDep, actor: ActorDep) -> Job:
        return call(lambda: service.get(session, actor, job_id))

    @router.post("/{job_id}/retry", name="retry_job")
    def retry(job_id: str, session: SessionDep, actor: ActorDep) -> Job:
        return call(lambda: service.retry(session, actor, job_id, datetime.now(UTC)))

    return router
