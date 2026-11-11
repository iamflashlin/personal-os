"""Runs action requests at most once per idempotency_key (ADR 0014, ADR 0015).

Every desktop call runs on one worker thread, in order. That thread is also where the
Windows adapter (T-0008) initialises COM. A handler that overruns its timeout is reported
as failed, but Python cannot stop the thread, so later actions wait behind it. The thread
is a daemon, so a stuck handler never keeps the agent process from exiting.
"""

import asyncio
import queue
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from apps.desktop_agent.actions import Done
from apps.desktop_agent.controller import DesktopController, DesktopUnavailable
from apps.desktop_agent.registry import REGISTRY, Handler
from packages.contracts.actions import (
    ACTION_SPECS,
    AUTO_APPROVED_RISKS,
    ActionName,
    ActionRequest,
    ActionResult,
    ActionStatus,
    parse_params,
)

CACHE_SIZE = 256
MAX_MESSAGE = 2000

_Job = tuple[Callable[[], Any], Future[Any]]


class _DesktopThread:
    """One daemon thread that runs jobs in order."""

    def __init__(self) -> None:
        self._jobs: queue.SimpleQueue[_Job | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._loop, name="desktop", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while (job := self._jobs.get()) is not None:
            fn, future = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn())
            except BaseException as exc:
                future.set_exception(exc)

    def submit(self, fn: Callable[[], Any]) -> Future[Any]:
        future: Future[Any] = Future()
        self._jobs.put((fn, future))
        return future

    def stop(self) -> None:
        self._jobs.put(None)


class Executor:
    def __init__(
        self,
        desktop: DesktopController,
        registry: Mapping[ActionName, Handler] = REGISTRY,
        *,
        cache_size: int = CACHE_SIZE,
        grace_s: float = 2.0,
    ) -> None:
        self._desktop = desktop
        self._registry = registry
        self._cache_size = cache_size
        self._grace_s = grace_s
        self._worker = _DesktopThread()
        # idempotency_key -> the (possibly still running) result of its one execution.
        self._seen: OrderedDict[str, asyncio.Future[ActionResult]] = OrderedDict()

    @property
    def cached_keys(self) -> int:
        return len(self._seen)

    async def execute(self, request: ActionRequest) -> ActionResult:
        key = request.idempotency_key
        earlier = self._seen.get(key)
        if earlier is not None:
            self._seen.move_to_end(key)
            first = await asyncio.shield(earlier)
            # Answer under this request's id, so the Hub can match it to its run.
            return first.model_copy(update={"replayed": True, "action_id": request.action_id})

        future: asyncio.Future[ActionResult] = asyncio.get_running_loop().create_future()
        self._seen[key] = future
        self._evict()
        started = datetime.now(UTC)
        done = Done(ActionStatus.failed, "agent stopped before the action finished")
        try:
            done = await self._run(request)
        except Exception as exc:  # anything unexpected still answers the Hub
            done = Done(ActionStatus.failed, f"agent error: {type(exc).__name__}")
        finally:
            # Settled even if this task is cancelled, so a replay never waits forever.
            result = ActionResult(
                action_id=request.action_id,
                idempotency_key=key,
                status=done.status,
                message=done.message[:MAX_MESSAGE],
                evidence=done.evidence[:20],
                started_at=started,
                finished_at=datetime.now(UTC),
            )
            future.set_result(result)
        return result

    def _evict(self) -> None:
        # Only settled entries go: dropping a running one would let a duplicate run again.
        while len(self._seen) > self._cache_size:
            oldest = next((k for k, f in self._seen.items() if f.done()), None)
            if oldest is None:
                return
            del self._seen[oldest]

    async def _run(self, request: ActionRequest) -> Done:
        handler = self._registry.get(request.name)
        spec = ACTION_SPECS.get(request.name)
        if handler is None or spec is None:
            return Done(ActionStatus.failed, f"unknown action {request.name}")
        if spec.risk not in AUTO_APPROVED_RISKS or request.risk_level not in AUTO_APPROVED_RISKS:
            return Done(ActionStatus.failed, f"{request.name} is not pre-approved on this agent")
        try:
            params = parse_params(request.name, request.params)
        except ValidationError as exc:
            problems = "; ".join(str(e["msg"]) for e in exc.errors())
            return Done(ActionStatus.failed, f"invalid params: {problems}")

        timeout_s = min(request.timeout_s, spec.timeout_s)
        work = self._worker.submit(lambda: handler(params, self._desktop, timeout_s))
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(work), timeout=timeout_s + self._grace_s
            )
        except TimeoutError:
            return Done(
                ActionStatus.failed,
                f"timed out after {timeout_s:g}s; it may still complete, check before retrying",
            )
        except DesktopUnavailable as exc:
            return Done(ActionStatus.needs_user, str(exc))
        except Exception as exc:
            return Done(ActionStatus.failed, f"{type(exc).__name__}: {exc}")

    def close(self) -> None:
        self._worker.stop()
