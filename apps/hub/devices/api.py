import asyncio
import logging
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Request, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from apps.hub.core.domain import Actor, DomainError
from apps.hub.core.http import ActorDep, SessionDep, call, run_in_session
from apps.hub.devices import service
from apps.hub.devices.links import AgentLink, AgentLinks
from packages.contracts.agent_protocol import (
    AGENT_TO_HUB,
    AGENT_WS_PATH,
    ActionResultMsg,
    AgentToHub,
    CloseCode,
    Heartbeat,
    HeartbeatAck,
    Hello,
    Welcome,
)
from packages.contracts.devices import AgentStatus, Device, PairingCode, PairRequest, PairResponse

# How many heartbeat intervals of silence end the connection.
SILENCE_LIMIT = 2

logger = logging.getLogger(__name__)


class _Close(Exception):
    def __init__(self, code: CloseCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _bearer(header: str | None) -> str | None:
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def _receive(websocket: WebSocket, timeout: float) -> AgentToHub:
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout)
    except TimeoutError as exc:
        raise _Close(CloseCode.heartbeat_timeout, "no heartbeat") from exc
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if text is None:
        raise _Close(CloseCode.protocol_error, "frames must be JSON text")
    try:
        return AGENT_TO_HUB.validate_json(text)
    except ValidationError as exc:
        raise _Close(CloseCode.protocol_error, "malformed message") from exc


async def _serve_agent(websocket: WebSocket, hooks: service.AgentHooks) -> None:
    state = websocket.app.state
    links: AgentLinks = state.agent_links
    owner_id: str = state.settings.owner_id
    interval: float = state.settings.agent_heartbeat_s
    engine = state.engine

    token = _bearer(websocket.headers.get("authorization"))
    device: Device | None = None
    # Browsers always send Origin and our agent never does, so any Origin is a web page.
    if token is not None and "origin" not in websocket.headers:
        device = await run_in_session(engine, lambda s: service.authenticate(s, owner_id, token))
    if device is None:
        # Closing before accept() makes the server answer the handshake with HTTP 403.
        await websocket.close(code=int(CloseCode.protocol_error))
        return

    await websocket.accept()
    actor = Actor(owner_id=owner_id, source="agent", device_id=device.id)
    try:
        hello = await _receive(websocket, interval * SILENCE_LIMIT)
        if not isinstance(hello, Hello):
            raise _Close(CloseCode.protocol_error, "the first message must be hello")
    except _Close as exc:
        await websocket.close(code=int(exc.code), reason=exc.reason)
        return
    except WebSocketDisconnect:
        return

    now = datetime.now(UTC)
    link = AgentLink(
        owner_id=owner_id,
        device_id=device.id,
        device_name=device.name,
        supported_actions=frozenset(hello.supported_actions),
        websocket=websocket,
        connected_at=now,
        last_heartbeat_at=now,
    )
    try:
        await run_in_session(
            engine, lambda s: service.record_connection(s, actor, device.id, connected=True)
        )
        # Welcome goes out before the link is live, so no action_request can overtake it.
        await link.send(Welcome(device_id=device.id, heartbeat_interval_s=interval))
        # No await between this check and attach(): a revoke either marked the device
        # already, or will find this link current and close it.
        if links.is_revoked(device.id):
            raise _Close(CloseCode.unauthorized, "device token revoked")
        previous = links.attach(link)
        if previous is not None:
            await previous.close(CloseCode.replaced, "a newer agent connected")
        while True:
            message = await _receive(websocket, interval * SILENCE_LIMIT)
            if isinstance(message, Heartbeat):
                link.last_heartbeat_at = datetime.now(UTC)
                await link.send(HeartbeatAck())
            elif isinstance(message, ActionResultMsg):
                result = message.result
                try:
                    await run_in_session(engine, lambda s, r=result: hooks.on_result(s, actor, r))
                except DomainError as exc:
                    # Keep the run in flight, so it becomes lost rather than stuck.
                    logger.warning("could not store result %s: %s", result.action_id, exc)
                else:
                    link.in_flight.discard(result.action_id)
            else:
                raise _Close(CloseCode.protocol_error, "hello may be sent only once")
    except _Close as exc:
        await link.close(exc.code, exc.reason)
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        # Starlette refuses to use a socket that another task (revoke, replace) closed.
        logger.info("agent link for %s ended: %s", device.id, exc)
    finally:
        links.detach(link)
        lost = set(link.in_flight)
        # Shielded: when the server cancels this task on shutdown, the lost runs and the
        # disconnect are still recorded. Lost runs first: they matter more.
        with anyio.CancelScope(shield=True):
            try:
                if lost:
                    await run_in_session(engine, lambda s: hooks.on_lost(s, actor, lost))
            except Exception:
                logger.exception("could not mark runs lost: %s", sorted(lost))
            try:
                await run_in_session(
                    engine,
                    lambda s: service.record_connection(s, actor, device.id, connected=False),
                )
            except Exception:
                logger.exception("could not record the disconnect of %s", device.id)


def build_router(hooks: service.AgentHooks) -> APIRouter:
    router = APIRouter(tags=["devices"])

    @router.post("/devices/pairing-codes", status_code=201, name="create_pairing_code")
    def create_pairing_code(session: SessionDep, actor: ActorDep) -> PairingCode:
        return call(lambda: service.create_pairing_code(session, actor))

    @router.post("/devices/pair", status_code=201, name="pair_device")
    def pair(request: PairRequest, session: SessionDep, actor: ActorDep) -> PairResponse:
        agent = Actor(owner_id=actor.owner_id, source="agent")
        return call(lambda: service.pair(session, agent, request))

    @router.get("/devices", name="list_devices")
    def list_devices(session: SessionDep, actor: ActorDep) -> list[Device]:
        return service.list_devices(session, actor)

    @router.post("/devices/{device_id}/revoke", name="revoke_device")
    async def revoke(device_id: str, request: Request, actor: ActorDep) -> Device:
        device = await run_in_session(
            request.app.state.engine, lambda s: call(lambda: service.revoke(s, actor, device_id))
        )
        links: AgentLinks = request.app.state.agent_links
        links.mark_revoked(device_id)
        link = links.current(actor.owner_id)
        if link is not None and link.device_id == device_id:
            links.detach(link)
            await link.close(CloseCode.unauthorized, "device token revoked")
        return device

    @router.get("/agent/status", name="agent_status")
    def agent_status(request: Request, actor: ActorDep) -> AgentStatus:
        return request.app.state.agent_links.status(actor.owner_id)

    @router.websocket(AGENT_WS_PATH)
    async def agent_ws(websocket: WebSocket) -> None:
        await _serve_agent(websocket, hooks)

    return router
