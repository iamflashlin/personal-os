"""The job service and worker with a hand-moved clock, so backoff and slots are exact."""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.domain import Actor, Invalid
from apps.hub.jobs import service
from apps.hub.jobs.worker import JobWorker
from packages.contracts.jobs import Job, JobStatus

T0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
ACTOR = Actor(owner_id="local", source="test")
BASE = timedelta(seconds=10)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(tmp_path)
    upgrade_to_head(engine)
    yield engine
    engine.dispose()


class Calls:
    """A handler that fails its first `failures` calls, then succeeds."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.payloads: list[dict[str, object]] = []

    def __call__(self, _engine: Engine, job: Job) -> None:
        self.payloads.append(job.payload)
        if len(self.payloads) <= self.failures:
            raise RuntimeError(f"attempt {len(self.payloads)} failed token=s3cret")


def setup(
    engine: Engine, calls: Calls, clock: Clock, owner: str = "local"
) -> tuple[JobWorker, service.JobKinds]:
    kinds = service.JobKinds()
    kinds.register("test.work", calls)
    return JobWorker(engine, owner, kinds, retry_base=BASE, clock=clock), kinds


def enqueue(engine: Engine, kind: str = "test.work", **kwargs: object) -> Job:
    with Session(engine) as s:
        return service.enqueue(s, ACTOR, kind, {"n": 1}, now=T0, **kwargs)  # type: ignore[arg-type]


def job(engine: Engine, job_id: str) -> Job:
    with Session(engine) as s:
        return service.get(s, ACTOR, job_id)


def tick(worker: JobWorker) -> int:
    return asyncio.run(worker.tick())


def test_a_job_runs_once_and_succeeds(engine: Engine) -> None:
    calls, clock = Calls(), Clock()
    worker, _ = setup(engine, calls, clock)
    queued = enqueue(engine)
    assert queued.status == JobStatus.queued
    assert tick(worker) == 1
    done = job(engine, queued.id)
    assert (done.status, done.attempts, done.last_error) == (JobStatus.succeeded, 1, "")
    assert calls.payloads == [{"n": 1}]
    assert tick(worker) == 0


def test_a_failing_job_is_retried_with_growing_delays_then_succeeds(engine: Engine) -> None:
    calls, clock = Calls(failures=2), Clock()
    worker, _ = setup(engine, calls, clock)
    queued = enqueue(engine)

    tick(worker)
    first = job(engine, queued.id)
    assert (first.status, first.attempts) == (JobStatus.queued, 1)
    assert first.run_at == T0 + BASE
    assert "attempt 1 failed" in first.last_error

    clock.advance(seconds=9)
    assert tick(worker) == 0  # not due yet
    clock.advance(seconds=1)
    tick(worker)
    second = job(engine, queued.id)
    assert second.run_at == clock.now + 2 * BASE  # doubled

    clock.advance(seconds=20)
    tick(worker)
    assert job(engine, queued.id).status == JobStatus.succeeded
    assert len(calls.payloads) == 3


def test_out_of_attempts_the_job_is_dead_with_its_last_error(engine: Engine) -> None:
    calls, clock = Calls(failures=99), Clock()
    worker, _ = setup(engine, calls, clock)
    queued = enqueue(engine, max_attempts=2)
    tick(worker)
    clock.advance(seconds=10)
    tick(worker)
    dead = job(engine, queued.id)
    assert (dead.status, dead.attempts) == (JobStatus.dead, 2)
    assert "attempt 2 failed" in dead.last_error
    assert "s3cret" not in dead.last_error  # errors are redacted before they are stored


def test_an_unknown_kind_is_dead_at_once(engine: Engine) -> None:
    worker, _ = setup(engine, Calls(), Clock())
    queued = enqueue(engine, kind="nobody.handles")
    tick(worker)
    dead = job(engine, queued.id)
    assert (dead.status, dead.attempts) == (JobStatus.dead, 1)
    assert "no handler" in dead.last_error


def test_one_job_per_idempotency_key(engine: Engine) -> None:
    first = enqueue(engine, idempotency_key="sync:2026-11-10")
    again = enqueue(engine, idempotency_key="sync:2026-11-10")
    assert again.id == first.id
    with Session(engine) as s, pytest.raises(Invalid):
        service.enqueue(s, ACTOR, "test.work", {"n": 2}, now=T0, idempotency_key="sync:2026-11-10")
    with Session(engine) as s:
        assert len(service.list_jobs(s, ACTOR)) == 1


def test_a_job_cut_off_by_a_crash_is_queued_again(engine: Engine) -> None:
    queued = enqueue(engine)
    with Session(engine) as s:
        service.claim_next(s, ACTOR, T0)  # running, and then the process died
    with Session(engine) as s:
        assert service.requeue_interrupted(s, ACTOR, T0, BASE) == 1
    back = job(engine, queued.id)
    assert (back.status, back.attempts, back.run_at) == (JobStatus.queued, 1, T0 + BASE)
    assert "restart" in back.last_error


def test_a_job_that_keeps_killing_the_hub_ends_up_dead(engine: Engine) -> None:
    queued = enqueue(engine, max_attempts=2)
    for restart in range(2):
        with Session(engine) as s:
            assert service.claim_next(s, ACTOR, T0 + timedelta(hours=restart)) is not None
        with Session(engine) as s:
            service.requeue_interrupted(s, ACTOR, T0 + timedelta(hours=restart), BASE)
    dead = job(engine, queued.id)
    assert (dead.status, dead.attempts) == (JobStatus.dead, 2)


def test_a_job_whose_ending_was_not_recorded_is_recovered_on_the_next_pass(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, clock = Calls(), Clock()
    worker, _ = setup(engine, calls, clock)
    queued = enqueue(engine)
    real_finish = service.finish

    def busy(*_args: object, **_kwargs: object) -> Job:
        raise OperationalError("UPDATE job", {}, Exception("database is locked"))

    monkeypatch.setattr(service, "finish", busy)
    with pytest.raises(OperationalError):
        tick(worker)
    assert job(engine, queued.id).status == JobStatus.running
    monkeypatch.setattr(service, "finish", real_finish)
    tick(worker)  # recovers it: queued again after the backoff
    assert job(engine, queued.id).status == JobStatus.queued
    clock.advance(seconds=10)
    tick(worker)
    assert job(engine, queued.id).status == JobStatus.succeeded


def test_one_broken_schedule_does_not_stop_the_others(engine: Engine) -> None:
    calls, clock = Calls(), Clock()
    worker, _ = setup(engine, calls, clock)
    with Session(engine) as s:
        service.ensure_schedule(s, ACTOR, "test.work", 60, {"n": 1}, now=T0)
        broken = service.ensure_schedule(s, ACTOR, "test.broken", 60, {"n": 1}, now=T0)
    slot_key = f"schedule:test.broken:{T0.isoformat()}"
    with Session(engine) as s:  # the slot's key is already taken by different work
        service.enqueue(s, ACTOR, "test.other", {"x": 1}, now=T0, idempotency_key=slot_key)
    tick(worker)
    assert calls.payloads == [{"n": 1}]  # the healthy schedule still ran
    with Session(engine) as s:
        events = audit.list_events(s, "local", broken.id)
    assert [e.result for e in events][-1] == "invalid"


def test_a_shorter_interval_takes_effect_now(engine: Engine) -> None:
    with Session(engine) as s:
        service.ensure_schedule(s, ACTOR, "test.work", 86400, {}, now=T0)
        service.fire_due_schedules(s, ACTOR, T0)  # next run is a day away
    with Session(engine) as s:
        shorter = service.ensure_schedule(s, ACTOR, "test.work", 900, {}, now=T0)
    assert shorter.next_run_at == T0 + timedelta(seconds=900)


def test_handler_errors_are_redacted_in_the_log(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    worker, _ = setup(engine, Calls(failures=1), Clock())
    enqueue(engine)
    with caplog.at_level("WARNING"):
        tick(worker)
    assert "attempt 1 failed" in caplog.text
    assert "s3cret" not in caplog.text


def test_a_schedule_enqueues_one_job_per_slot_and_coalesces_downtime(engine: Engine) -> None:
    calls, clock = Calls(), Clock()
    worker, _ = setup(engine, calls, clock)
    with Session(engine) as s:
        service.ensure_schedule(s, ACTOR, "test.work", 60, {"n": 1}, now=T0)
    tick(worker)  # slot 08:00
    tick(worker)  # nothing new in the same minute
    clock.advance(seconds=60)
    tick(worker)  # slot 08:01
    clock.advance(hours=3)  # the Hub was down; 180 slots were missed
    tick(worker)  # one catch-up run, not 180
    with Session(engine) as s:
        keys = sorted(j.idempotency_key or "" for j in service.list_jobs(s, ACTOR))
        (schedule,) = service.list_schedules(s, ACTOR)
    assert len(keys) == 3 and len(set(keys)) == 3
    assert len(calls.payloads) == 3
    assert schedule.next_run_at == clock.now + timedelta(seconds=60)


def test_ensuring_the_same_schedule_twice_writes_nothing(engine: Engine) -> None:
    with Session(engine) as s:
        first = service.ensure_schedule(s, ACTOR, "test.work", 900, {"box": "inbox"}, now=T0)
    with Session(engine) as s:
        again = service.ensure_schedule(s, ACTOR, "test.work", 900, {"box": "inbox"}, now=T0)
        events = audit.list_events(s, "local", first.id)
    assert again == first
    assert [e.action for e in events] == ["job_schedule.ensure"]


def test_jobs_belong_to_their_owner(engine: Engine) -> None:
    calls, clock = Calls(), Clock()
    other_worker, _ = setup(engine, calls, clock, owner="someone-else")
    enqueue(engine)
    assert tick(other_worker) == 0
    with Session(engine) as s:
        assert service.list_jobs(s, Actor(owner_id="someone-else")) == []


def test_each_write_is_audited_once_with_secrets_redacted(engine: Engine) -> None:
    calls, clock = Calls(failures=1), Clock()
    worker, _ = setup(engine, calls, clock)
    with Session(engine) as s:
        queued = service.enqueue(s, ACTOR, "test.work", {"password": "hunter2"}, now=T0)
    tick(worker)
    clock.advance(seconds=10)
    tick(worker)
    with Session(engine) as s:
        events = audit.list_events(s, "local", queued.id)
    assert [(e.action, e.result) for e in events] == [
        ("job.enqueue", "ok"),
        ("job.start", "ok"),
        ("job.finish", "retry"),
        ("job.start", "ok"),
        ("job.finish", "succeeded"),
    ]
    logged = json.dumps([e.detail for e in events])
    assert "hunter2" not in logged and "s3cret" not in logged


def test_the_worker_stops_at_once_even_while_a_handler_runs(engine: Engine) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(_engine: Engine, _job: Job) -> None:
        started.set()
        release.wait(10)

    kinds = service.JobKinds()
    kinds.register("test.work", slow)
    worker = JobWorker(engine, "local", kinds, poll_s=0.05)

    async def go() -> float:
        worker.start()
        with Session(engine) as s:
            queued = service.enqueue(s, ACTOR, "test.work", {}, now=datetime.now(UTC))
        deadline = time.monotonic() + 10
        while not started.is_set():
            assert time.monotonic() < deadline, "the handler never started"
            await asyncio.sleep(0.02)
        began = time.monotonic()
        await worker.stop()
        stopped_in = time.monotonic() - began
        assert not worker.running
        assert job(engine, queued.id).status == JobStatus.running  # requeued at next start
        release.set()
        return stopped_in

    assert asyncio.run(go()) < 1.0
