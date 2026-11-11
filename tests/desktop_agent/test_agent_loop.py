"""The agent loop against the real Hub app served by uvicorn on a free local port."""

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from apps.desktop_agent.config import AgentConfig
from apps.desktop_agent.connection import AgentExit, run_agent
from apps.desktop_agent.executor import Executor
from apps.desktop_agent.token_store import MemoryTokenStore
from packages.contracts.agent_protocol import Welcome
from tests.desktop_agent.fakes import FakeDesktop, HubThread

OPEN_URL = {
    "name": "open_url",
    "params": {"url": "https://example.com/plan", "expect_title_contains": "Plan"},
}


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[HubThread]:
    server = HubThread(tmp_path / "data")
    server.start()
    yield server
    server.stop()


class Agent:
    """One run_agent task plus what it saw."""

    def __init__(self, hub: HubThread, token: str, desktop: FakeDesktop) -> None:
        self.welcomes: list[Welcome] = []
        self.connected = asyncio.Event()
        self.executor = Executor(desktop)
        config = AgentConfig(hub_url=hub.url, backoff_base_s=0.05, backoff_cap_s=0.3)
        self.task = asyncio.create_task(
            run_agent(config, MemoryTokenStore(token), self.executor, on_connected=self._on)
        )

    def _on(self, welcome: Welcome) -> None:
        self.welcomes.append(welcome)
        self.connected.set()

    async def wait_connected(self, times: int = 1) -> None:
        async def reached() -> None:
            while len(self.welcomes) < times:
                await self.connected.wait()
                self.connected.clear()

        await asyncio.wait_for(reached(), 15)

    async def exit_code(self) -> AgentExit:
        try:
            return await asyncio.wait_for(self.task, 10)
        finally:
            self.executor.close()

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.executor.close()


async def pair(http: httpx.AsyncClient, name: str = "agent") -> tuple[str, str]:
    code = (await http.post("/devices/pairing-codes")).json()["code"]
    paired = await http.post(
        "/devices/pair", json={"code": code, "device_name": name, "platform": "windows"}
    )
    assert paired.status_code == 201, paired.text
    return paired.json()["device_id"], paired.json()["token"]


async def until(check: Callable[[], Awaitable[bool]], what: str, timeout: float = 10) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await check():
        assert asyncio.get_running_loop().time() < deadline, f"timed out waiting: {what}"
        await asyncio.sleep(0.05)


def scenario(hub: HubThread, body: Callable[[httpx.AsyncClient], Awaitable[None]]) -> None:
    async def go() -> None:
        async with httpx.AsyncClient(base_url=hub.url, timeout=10) as http:
            await body(http)

    asyncio.run(go())


def test_pair_connect_heartbeat_and_an_action_round_trip(hub: HubThread) -> None:
    desktop = FakeDesktop()

    async def body(http: httpx.AsyncClient) -> None:
        device_id, token = await pair(http)
        agent = Agent(hub, token, desktop)
        await agent.wait_connected()
        assert agent.welcomes[0].device_id == device_id
        first = (await http.get("/agent/status")).json()
        assert first["online"] and first["device_id"] == device_id

        async def heartbeat_advanced() -> bool:
            now = (await http.get("/agent/status")).json()
            return now["last_heartbeat_at"] != first["last_heartbeat_at"]

        await until(heartbeat_advanced, "a heartbeat reached the Hub")

        created = await http.post("/actions", json=OPEN_URL, headers={"Idempotency-Key": "a1"})
        assert created.status_code == 202, created.text
        run_id = created.json()["id"]

        async def succeeded() -> bool:
            return (await http.get(f"/actions/{run_id}")).json()["status"] == "succeeded"

        await until(succeeded, "the result was stored")
        stored = (await http.get(f"/actions/{run_id}")).json()
        assert stored["evidence"][0]["data"] == {"title": "Plan - Window", "pid": 4242}

        replay = await http.post("/actions", json=OPEN_URL, headers={"Idempotency-Key": "a1"})
        assert replay.headers["Idempotent-Replayed"] == "true"
        await asyncio.sleep(0.5)
        assert desktop.count("open_url") == 1
        await agent.stop()

    scenario(hub, body)


def test_the_agent_reconnects_after_a_hub_restart(hub: HubThread) -> None:
    async def body(http: httpx.AsyncClient) -> None:
        _, token = await pair(http)
        agent = Agent(hub, token, FakeDesktop())
        await agent.wait_connected()
        await asyncio.to_thread(hub.restart)
        await agent.wait_connected(times=2)
        assert (await http.get("/agent/status")).json()["online"]
        await agent.stop()

    scenario(hub, body)


def test_a_revoked_token_stops_the_agent_for_good(hub: HubThread) -> None:
    async def body(http: httpx.AsyncClient) -> None:
        device_id, token = await pair(http)
        agent = Agent(hub, token, FakeDesktop())
        await agent.wait_connected()
        assert (await http.post(f"/devices/{device_id}/revoke")).status_code == 200
        assert await agent.exit_code() == AgentExit.auth_rejected
        assert len(agent.welcomes) == 1

        again = Agent(hub, token, FakeDesktop())
        assert await again.exit_code() == AgentExit.auth_rejected
        assert again.welcomes == []

    scenario(hub, body)


def test_a_newer_agent_replaces_the_older_one(hub: HubThread) -> None:
    async def body(http: httpx.AsyncClient) -> None:
        _, old_token = await pair(http, "old")
        new_id, new_token = await pair(http, "new")
        old = Agent(hub, old_token, FakeDesktop())
        await old.wait_connected()
        new = Agent(hub, new_token, FakeDesktop())
        await new.wait_connected()
        assert await old.exit_code() == AgentExit.replaced
        assert (await http.get("/agent/status")).json()["device_id"] == new_id
        await new.stop()

    scenario(hub, body)


def test_an_unpaired_agent_exits_without_connecting(hub: HubThread) -> None:
    async def body(_http: httpx.AsyncClient) -> None:
        config = AgentConfig(hub_url=hub.url)
        executor = Executor(FakeDesktop())
        try:
            assert await run_agent(config, MemoryTokenStore(), executor) == AgentExit.not_paired
        finally:
            executor.close()

    scenario(hub, body)


def test_a_result_finished_while_offline_is_delivered_after_reconnecting(
    hub: HubThread,
) -> None:
    gate = threading.Event()
    desktop = FakeDesktop(gate=gate)

    async def body(http: httpx.AsyncClient) -> None:
        _, token = await pair(http)
        agent = Agent(hub, token, desktop)
        await agent.wait_connected()
        created = await http.post("/actions", json=OPEN_URL, headers={"Idempotency-Key": "late"})
        run_id = created.json()["id"]

        async def started() -> bool:
            return desktop.count("open_url") == 1

        await until(started, "the action started")
        await asyncio.to_thread(hub.stop)  # the run is lost while the agent works
        gate.set()  # the action finishes while no Hub is listening

        async def finished() -> bool:
            return desktop.count("wait_for_window") == 1  # its last desktop call

        await until(finished, "the action finished while the Hub was down")
        await asyncio.to_thread(hub.start)
        await agent.wait_connected(times=2)

        async def recorded() -> bool:
            run: dict[str, Any] = (await http.get(f"/actions/{run_id}")).json()
            return run["status"] == "succeeded"

        await until(recorded, "the late result reached the restarted Hub")
        await agent.stop()

    scenario(hub, body)
