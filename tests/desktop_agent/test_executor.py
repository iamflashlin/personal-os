import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from ulid import ULID

from apps.desktop_agent.actions import Done
from apps.desktop_agent.backoff import Backoff
from apps.desktop_agent.controller import UnsupportedController
from apps.desktop_agent.executor import Executor
from apps.desktop_agent.registry import REGISTRY
from packages.contracts.actions import (
    ACTION_SPECS,
    ActionName,
    ActionRequest,
    ActionResult,
    ActionStatus,
    RiskLevel,
)
from tests.desktop_agent.fakes import FakeDesktop

URL = {"url": "https://example.com/plan", "expect_title_contains": "Plan"}
FOLDER = {"path": "D:\\dev\\notes"}


def request(
    name: ActionName = ActionName.open_url,
    params: dict[str, Any] | None = None,
    key: str = "k-1",
    timeout_s: float = 5,
    risk: RiskLevel = RiskLevel.P1,
) -> ActionRequest:
    return ActionRequest(
        action_id=str(ULID()),
        idempotency_key=key,
        name=name,
        params=URL if params is None else params,
        risk_level=risk,
        timeout_s=timeout_s,
        issued_at=datetime.now(UTC),
    )


def execute(executor: Executor, *requests: ActionRequest) -> list[ActionResult]:
    async def go() -> list[ActionResult]:
        return list(await asyncio.gather(*(executor.execute(r) for r in requests)))

    try:
        return asyncio.run(go())
    finally:
        executor.close()


def test_the_registry_covers_exactly_the_contract_whitelist() -> None:
    assert set(REGISTRY) == set(ACTION_SPECS)


def test_open_url_opens_then_verifies_the_window() -> None:
    desktop = FakeDesktop()
    (result,) = execute(Executor(desktop), request())
    assert result.status == ActionStatus.succeeded
    assert desktop.calls == [
        ("open_url", "https://example.com/plan"),
        ("wait_for_window", "Plan"),
    ]
    assert result.evidence[0].data == {"title": "Plan - Window", "pid": 4242}


def test_a_window_that_never_appears_is_a_failure() -> None:
    (result,) = execute(Executor(FakeDesktop(windows=False)), request())
    assert result.status == ActionStatus.failed
    assert result.evidence == []


def test_open_folder_spawns_code_with_an_argument_list() -> None:
    desktop = FakeDesktop()
    (result,) = execute(
        Executor(desktop), request(ActionName.open_folder_in_editor, FOLDER, timeout_s=30)
    )
    assert result.status == ActionStatus.succeeded
    assert ("spawn", desktop.code_path, "--new-window", "D:\\dev\\notes") in desktop.calls
    assert ("wait_for_window", "notes") in desktop.calls


def test_a_missing_code_cli_needs_the_user_and_starts_nothing() -> None:
    desktop = FakeDesktop(code_path=None)
    (result,) = execute(Executor(desktop), request(ActionName.open_folder_in_editor, FOLDER))
    assert result.status == ActionStatus.needs_user
    assert desktop.count("spawn") == 0


@pytest.mark.parametrize("path", ["D:\\a & calc", "D:\\a|b", "\\\\host\\share", "notes"])
def test_bad_folder_paths_fail_before_any_desktop_call(path: str) -> None:
    desktop = FakeDesktop()
    (result,) = execute(
        Executor(desktop), request(ActionName.open_folder_in_editor, {"path": path})
    )
    assert result.status == ActionStatus.failed
    assert result.message.startswith("invalid params")
    assert desktop.calls == []


def test_an_action_missing_from_the_registry_fails() -> None:
    registry = {ActionName.open_url: REGISTRY[ActionName.open_url]}
    desktop = FakeDesktop()
    (result,) = execute(
        Executor(desktop, registry), request(ActionName.open_folder_in_editor, FOLDER)
    )
    assert result.status == ActionStatus.failed
    assert desktop.calls == []


def test_a_request_claiming_a_higher_risk_is_refused() -> None:
    desktop = FakeDesktop()
    (result,) = execute(Executor(desktop), request(risk=RiskLevel.P3))
    assert result.status == ActionStatus.failed
    assert desktop.calls == []


def test_an_overrunning_action_times_out_as_failed() -> None:
    def slow(_params: Any, _desktop: Any, _timeout: float) -> Done:
        time.sleep(1.0)
        return Done(ActionStatus.succeeded, "too late")

    registry = {**REGISTRY, ActionName.open_url: slow}
    started = time.monotonic()
    (result,) = execute(Executor(FakeDesktop(), registry, grace_s=0), request(timeout_s=0.1))
    assert result.status == ActionStatus.failed
    assert "timed out" in result.message
    assert time.monotonic() - started < 0.9


def test_a_machine_without_a_desktop_adapter_needs_the_user() -> None:
    (result,) = execute(Executor(UnsupportedController()), request())
    assert result.status == ActionStatus.needs_user


def test_a_crashing_handler_still_answers_failed() -> None:
    def boom(_params: Any, _desktop: Any, _timeout: float) -> Done:
        raise RuntimeError("adapter bug")

    registry = {**REGISTRY, ActionName.open_url: boom}
    (result,) = execute(Executor(FakeDesktop(), registry), request())
    assert result.status == ActionStatus.failed
    assert "adapter bug" in result.message


def test_the_same_key_executes_once_sequentially() -> None:
    desktop = FakeDesktop()
    executor = Executor(desktop)

    async def go() -> list[ActionResult]:
        return [await executor.execute(request(key="same")) for _ in range(3)]

    try:
        first, *replays = asyncio.run(go())
    finally:
        executor.close()
    assert desktop.count("open_url") == 1
    assert not first.replayed
    assert all(r.replayed and r.status == first.status for r in replays)


def test_the_same_key_executes_once_concurrently() -> None:
    desktop = FakeDesktop(delay_s=0.2)
    results = execute(Executor(desktop), *(request(key="same") for _ in range(5)))
    assert desktop.count("open_url") == 1
    assert [r.replayed for r in results].count(False) == 1


def test_different_keys_each_execute() -> None:
    desktop = FakeDesktop()
    execute(Executor(desktop), request(key="a"), request(key="b"))
    assert desktop.count("open_url") == 2


def test_the_key_cache_is_bounded() -> None:
    desktop = FakeDesktop()
    executor = Executor(desktop, cache_size=3)

    async def go() -> None:
        for key in "abcde":
            await executor.execute(request(key=key))
        assert executor.cached_keys == 3
        await executor.execute(request(key="e"))  # still cached
        await executor.execute(request(key="a"))  # evicted: runs again

    try:
        asyncio.run(go())
    finally:
        executor.close()
    assert desktop.count("open_url") == 6


def test_backoff_grows_within_bounds_and_resets() -> None:
    top = Backoff(base_s=0.5, cap_s=30, rand=lambda: 1.0)
    assert [top.next() for _ in range(8)] == [0.5, 1, 2, 4, 8, 16, 30, 30]
    top.reset()
    assert top.next() == 0.5
    bottom = Backoff(base_s=0.5, cap_s=30, rand=lambda: 0.0)
    assert {bottom.next() for _ in range(50)} == {0.0}
    real = Backoff(base_s=0.5, cap_s=30)
    assert all(0 <= real.next() <= 30 for _ in range(200))


def test_a_running_key_is_never_evicted_so_it_cannot_run_twice() -> None:
    gate = threading.Event()
    desktop = FakeDesktop(gate=gate)
    executor = Executor(desktop, cache_size=1)

    async def go() -> list[ActionResult]:
        slow = asyncio.create_task(executor.execute(request(key="slow")))
        await asyncio.sleep(0.1)
        other = asyncio.create_task(executor.execute(request(key="other")))
        await asyncio.sleep(0.1)  # "other" is queued behind "slow"; "slow" stays cached
        again = asyncio.create_task(executor.execute(request(key="slow")))
        gate.set()
        return list(await asyncio.gather(slow, other, again))

    try:
        first, _, again = asyncio.run(go())
    finally:
        executor.close()
    assert desktop.count("open_url") == 2  # "slow" once, "other" once
    assert again.replayed and again.status == first.status
