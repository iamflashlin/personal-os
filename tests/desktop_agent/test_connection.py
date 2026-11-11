"""The agent loop against scripted fake Hubs, for paths a real Hub never takes on purpose."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from ulid import ULID
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from apps.desktop_agent.config import AgentConfig
from apps.desktop_agent.connection import AgentExit, _Agent, run_agent
from apps.desktop_agent.executor import Executor
from apps.desktop_agent.token_store import MemoryTokenStore
from packages.contracts.actions import (
    ActionName,
    ActionRequest,
    ActionResult,
    ActionStatus,
    RiskLevel,
)
from packages.contracts.agent_protocol import (
    AGENT_TO_HUB,
    ActionRequestMsg,
    ActionResultMsg,
    CloseCode,
    Hello,
    Welcome,
)
from tests.desktop_agent.fakes import FakeDesktop


def config(port: int) -> AgentConfig:
    return AgentConfig(hub_url=f"http://127.0.0.1:{port}", backoff_base_s=0.02, backoff_cap_s=0.1)


def a_request() -> ActionRequest:
    return ActionRequest(
        action_id=str(ULID()),
        idempotency_key="same-key",
        name=ActionName.open_url,
        params={"url": "https://example.com/", "expect_title_contains": "Example"},
        risk_level=RiskLevel.P1,
        timeout_s=5,
        issued_at=datetime.now(UTC),
    )


def a_result() -> ActionResult:
    now = datetime.now(UTC)
    return ActionResult(
        action_id=str(ULID()),
        idempotency_key="k",
        status=ActionStatus.succeeded,
        started_at=now,
        finished_at=now,
    )


def test_a_request_delivered_twice_on_the_socket_executes_once() -> None:
    desktop = FakeDesktop()
    results: list[ActionResultMsg] = []

    async def fake_hub(ws: ServerConnection) -> None:
        hello = AGENT_TO_HUB.validate_json(await ws.recv())
        assert isinstance(hello, Hello)
        await ws.send(Welcome(device_id=str(ULID()), heartbeat_interval_s=5).model_dump_json())
        request = a_request()
        twin = request.model_copy(update={"action_id": str(ULID())})
        await ws.send(ActionRequestMsg(request=request).model_dump_json())
        await ws.send(ActionRequestMsg(request=twin).model_dump_json())
        while len(results) < 2:
            message = AGENT_TO_HUB.validate_json(await ws.recv())
            if isinstance(message, ActionResultMsg):
                results.append(message)
        await ws.close(int(CloseCode.replaced), "done")

    async def go() -> AgentExit:
        async with serve(fake_hub, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            executor = Executor(desktop)
            try:
                return await asyncio.wait_for(
                    run_agent(config(port), MemoryTokenStore("posd_x"), executor), 10
                )
            finally:
                executor.close()

    assert asyncio.run(go()) == AgentExit.replaced
    assert desktop.count("open_url") == 1
    first, second = (m.result for m in results)
    assert (first.replayed, second.replayed) == (False, True)
    assert first.action_id != second.action_id  # each answer matches its own request


def test_a_hub_that_hangs_up_mid_handshake_is_retried_not_fatal() -> None:
    attempts = 0

    async def hang_up(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal attempts
        attempts += 1
        writer.close()

    async def go() -> None:
        server = await asyncio.start_server(hang_up, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        executor = Executor(FakeDesktop())
        task = asyncio.create_task(run_agent(config(port), MemoryTokenStore("posd_x"), executor))
        try:
            while attempts < 3:
                assert not task.done(), f"run_agent ended: {task.result()!r}"
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            executor.close()
            server.close()

    asyncio.run(asyncio.wait_for(go(), 10))


class DeadSocket:
    """A connection whose every send fails, like websockets after the link dropped."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.sends = 0

    async def send(self, _text: str) -> None:
        self.sends += 1
        raise self.error


def make_agent(ws: Any) -> _Agent:
    agent = _Agent(Executor(FakeDesktop()))
    agent.ws = ws
    return agent


def test_flushing_into_a_dead_socket_stops_at_the_first_failure() -> None:
    dead = DeadSocket(ConnectionClosed(None, None))
    agent = make_agent(dead)
    agent.unsent.extend([a_result(), a_result()])

    async def go() -> None:
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(agent.flush_unsent(), 1)

    asyncio.run(go())
    assert dead.sends == 1
    assert len(agent.unsent) == 2  # nothing lost, nothing reordered


@pytest.mark.parametrize("ws", [None, DeadSocket(RuntimeError("unexpected"))])
def test_a_result_that_cannot_be_sent_is_kept_never_dropped(ws: Any) -> None:
    agent = make_agent(ws)
    result = a_result()
    assert asyncio.run(agent.deliver(result)) is False
    assert list(agent.unsent) == [result]
