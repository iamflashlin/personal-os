"""The agent's side of /agent/ws: connect out, stay connected, answer action requests.

The agent always dials the Hub (ADR 0007). It reconnects with jittered backoff after any
network failure, and stops for good when the Hub says its token is no good or that a
newer agent took over.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from enum import IntEnum

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from apps.desktop_agent.backoff import Backoff
from apps.desktop_agent.config import AGENT_VERSION, AgentConfig, this_platform
from apps.desktop_agent.executor import Executor
from apps.desktop_agent.registry import REGISTRY
from apps.desktop_agent.token_store import TokenStore
from packages.contracts.actions import ActionResult
from packages.contracts.agent_protocol import (
    HUB_TO_AGENT,
    ActionRequestMsg,
    ActionResultMsg,
    AgentToHub,
    CloseCode,
    Heartbeat,
    Hello,
    HubToAgent,
    Welcome,
)

logger = logging.getLogger(__name__)

# Silence from the Hub for this many heartbeat intervals means the link is dead.
SILENCE_LIMIT = 3
# Results that could not be sent wait for the next connection; the Hub accepts a late
# result, even for a run it already marked lost (ADR 0014).
UNSENT_LIMIT = 100
MIN_HEARTBEAT_S = 0.2


class AgentExit(IntEnum):
    """Process exit codes of `python -m apps.desktop_agent run`."""

    stopped = 0
    not_paired = 2
    auth_rejected = 3  # revoked or unknown token: pair again
    replaced = 4  # a newer agent for this owner connected


class _ProtocolError(Exception):
    pass


class _Agent:
    """State that outlives one connection: running actions and unsent results."""

    def __init__(self, executor: Executor) -> None:
        self.executor = executor
        self.ws: ClientConnection | None = None
        self.unsent: deque[ActionResult] = deque(maxlen=UNSENT_LIMIT)
        self.tasks: set[asyncio.Task[None]] = set()  # strong refs: asyncio keeps weak ones
        self._lock = asyncio.Lock()

    async def send(self, message: AgentToHub) -> None:
        async with self._lock:
            # Read under the lock: the session may end while this task waited for it.
            ws = self.ws
            if ws is None:
                raise ConnectionError("not connected")
            await ws.send(message.model_dump_json())

    def keep(self, result: ActionResult) -> None:
        if len(self.unsent) == self.unsent.maxlen:
            logger.warning("too many unsent results; dropping the oldest")
        self.unsent.append(result)

    async def deliver(self, result: ActionResult) -> bool:
        """Send one result, or keep it for the next connection. Never loses it."""
        try:
            await self.send(ActionResultMsg(result=result))
        except Exception as exc:
            if not isinstance(exc, ConnectionClosed | ConnectionError):
                logger.exception("sending result %s failed", result.action_id)
            self.keep(result)
            return False
        return True

    async def flush_unsent(self) -> None:
        """Send what is waiting, oldest first; stop at the first failure."""
        while self.unsent:
            result = self.unsent.popleft()
            try:
                await self.send(ActionResultMsg(result=result))
            except Exception:
                self.unsent.appendleft(result)
                raise

    def start(self, request: ActionRequestMsg) -> None:
        async def answer() -> None:
            await self.deliver(await self.executor.execute(request.request))

        task = asyncio.create_task(answer())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


async def run_agent(
    config: AgentConfig,
    tokens: TokenStore,
    executor: Executor,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_connected: Callable[[Welcome], None] | None = None,
) -> AgentExit:
    token = tokens.get()
    if token is None:
        return AgentExit.not_paired
    agent = _Agent(executor)
    backoff = Backoff(config.backoff_base_s, config.backoff_cap_s)
    headers = {"Authorization": f"Bearer {token}"}
    loop = asyncio.get_running_loop()
    while True:
        try:
            async with connect(
                config.ws_url, additional_headers=headers, open_timeout=10, max_size=2**20
            ) as ws:
                welcome = await _handshake(ws)
                logger.info("connected as device %s", welcome.device_id)
                if on_connected is not None:
                    on_connected(welcome)
                agent.ws = ws
                up_since = loop.time()
                try:
                    await _session(ws, _interval(welcome), agent)
                finally:
                    agent.ws = None
                    # Reset only after a link that stayed up: a Hub that welcomes and then
                    # closes at once must not be redialled in a tight loop.
                    if loop.time() - up_since >= _interval(welcome):
                        backoff.reset()
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status in (401, 403):
                logger.warning("the Hub refused this agent's token (HTTP %s)", status)
                return AgentExit.auth_rejected
            logger.info("handshake refused with HTTP %s; retrying", status)
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd is not None else None
            if code == CloseCode.unauthorized:
                logger.warning("the Hub revoked this agent's token")
                return AgentExit.auth_rejected
            if code == CloseCode.replaced:
                logger.warning("a newer agent connected; this one stops")
                return AgentExit.replaced
            logger.info("connection closed (%s); reconnecting", code)
        except (_ProtocolError, ValidationError, InvalidHandshake) as exc:
            # InvalidHandshake: e.g. a Hub that died mid-handshake, or something else on
            # the port. Only 401/403 (handled above) mean the token is bad.
            logger.warning("protocol error (%s); reconnecting", type(exc).__name__)
        except (OSError, TimeoutError) as exc:
            logger.info("Hub unreachable (%s); retrying", type(exc).__name__)
        await sleep(backoff.next())


async def _recv(ws: ClientConnection, timeout: float) -> HubToAgent:
    return HUB_TO_AGENT.validate_json(await asyncio.wait_for(ws.recv(), timeout))


async def _handshake(ws: ClientConnection) -> Welcome:
    hello = Hello(
        agent_version=AGENT_VERSION, platform=this_platform(), supported_actions=sorted(REGISTRY)
    )
    await ws.send(hello.model_dump_json())
    first = await _recv(ws, 10)
    if not isinstance(first, Welcome):
        raise _ProtocolError(f"expected welcome, got {first.type}")
    return first


def _interval(welcome: Welcome) -> float:
    """The Hub's heartbeat interval, clamped so a bad value cannot make us spin."""
    return min(max(welcome.heartbeat_interval_s, MIN_HEARTBEAT_S), 300.0)


async def _session(ws: ClientConnection, interval: float, agent: _Agent) -> None:
    async def heartbeats() -> None:
        while True:
            await asyncio.sleep(interval)
            await agent.send(Heartbeat())

    await agent.flush_unsent()
    beating = asyncio.create_task(heartbeats())
    try:
        while True:
            try:
                message = await _recv(ws, interval * SILENCE_LIMIT)
            except TimeoutError:
                logger.info("no message from the Hub for a while; reconnecting")
                return
            if isinstance(message, ActionRequestMsg):
                logger.info("action %s (%s)", message.request.name, message.request.action_id)
                agent.start(message)
    finally:
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError, ConnectionClosed, ConnectionError):
            await beating
