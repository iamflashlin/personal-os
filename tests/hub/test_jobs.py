"""The jobs HTTP API and the worker inside the running Hub app."""

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.jobs import service
from apps.hub.main import job_kinds
from packages.contracts.jobs import JobStatus
from tests.hub.support import hub_client

ACTOR = Actor(owner_id="local", source="test")
MISSING = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def enqueue(client: TestClient, kind: str, **kwargs: object) -> str:
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        job = service.enqueue(s, ACTOR, kind, {}, now=datetime.now(UTC), **kwargs)  # type: ignore[arg-type]
    return job.id


def wait_for(client: TestClient, job_id: str, status: JobStatus) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        assert time.monotonic() < deadline, f"job stayed {job['status']}"
        time.sleep(0.05)


def fast(data_dir: Path) -> Settings:
    return Settings(data_dir=data_dir, jobs_poll_s=0.05, jobs_retry_base_s=0.05)


def test_the_hub_runs_its_built_in_job(data_dir: Path) -> None:
    with hub_client(fast(data_dir)) as client:
        job_id = enqueue(client, "system.noop")
        done = wait_for(client, job_id, JobStatus.succeeded)
        assert done["attempts"] == 1
        listed = client.get("/jobs", params={"status": "succeeded"}).json()
        assert [j["id"] for j in listed] == [job_id]


def test_a_dead_job_can_be_retried_by_hand(data_dir: Path) -> None:
    with hub_client(fast(data_dir)) as client:
        job_id = enqueue(client, "nobody.handles")
        wait_for(client, job_id, JobStatus.dead)
        assert client.post(f"/jobs/{job_id}/retry").status_code == 200
        dead_again = wait_for(client, job_id, JobStatus.dead)
        assert dead_again["attempts"] == 1  # a retry starts a fresh set of attempts


def test_only_a_dead_job_can_be_retried(data_dir: Path) -> None:
    with hub_client(fast(data_dir)) as client:
        job_id = enqueue(client, "system.noop")
        wait_for(client, job_id, JobStatus.succeeded)
        assert client.post(f"/jobs/{job_id}/retry").status_code == 409
        assert client.post(f"/jobs/{MISSING}/retry").status_code == 404
        assert client.get(f"/jobs/{MISSING}").status_code == 404


def test_schedules_are_listed(data_dir: Path) -> None:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False)) as client:
        with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
            service.ensure_schedule(s, ACTOR, "system.noop", 900, {}, now=datetime.now(UTC))
        (schedule,) = client.get("/jobs/schedules").json()
        assert (schedule["kind"], schedule["interval_s"]) == ("system.noop", 900)


def test_a_job_left_running_by_a_crash_runs_after_restart(data_dir: Path) -> None:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False)) as client:
        job_id = enqueue(client, "system.noop")
        with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
            service.claim_next(s, ACTOR, datetime.now(UTC))
        assert client.get(f"/jobs/{job_id}").json()["status"] == "running"
    with hub_client(fast(data_dir)) as client:
        done = wait_for(client, job_id, JobStatus.succeeded)
        assert done["attempts"] == 2  # the interrupted attempt still counts
    assert done["last_error"] == ""


def test_every_job_kind_is_registered_once() -> None:
    kinds = job_kinds()
    assert kinds.get("system.noop") is not None
    with pytest.raises(ValueError, match="already registered"):
        kinds.register("system.noop", lambda _e, _j: None)


def test_the_worker_starts_and_stops_with_the_hub(data_dir: Path) -> None:
    with hub_client(fast(data_dir)) as client:
        worker = client.app.state.job_worker  # type: ignore[attr-defined]
        assert worker.running
    assert not worker.running
