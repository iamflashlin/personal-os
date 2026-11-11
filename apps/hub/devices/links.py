"""The live agent connections, in memory: one per owner, the newest wins (ADR 0014).

Everything here runs on the server's single event loop, which is why the Hub runs one
uvicorn worker.
"""

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime

from starlette.websockets import WebSocket

from packages.contracts.actions import ActionName
from packages.contracts.agent_protocol import CloseCode, HubToAgent
from packages.contracts.devices import AgentStatus


@dataclass(eq=False)
class AgentLink:
    owner_id: str
    device_id: str
    device_name: str
    supported_actions: frozenset[ActionName]
    websocket: WebSocket
    connected_at: datetime
    last_heartbeat_at: datetime
    # Action runs sent on this connection and not yet answered. When it drops, exactly
    # these become `lost`, never runs a newer connection of the same device was given.
    in_flight: set[str] = field(default_factory=set[str])
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: HubToAgent) -> None:
        async with self._send_lock:
            await self.websocket.send_text(message.model_dump_json())

    async def close(self, code: CloseCode, reason: str) -> None:
        """Close from the Hub's side; a socket that is already gone is not an error."""
        with contextlib.suppress(RuntimeError, OSError):
            await self.websocket.close(code=int(code), reason=reason)


class AgentLinks:
    def __init__(self) -> None:
        self._by_owner: dict[str, AgentLink] = {}
        # Devices revoked while this process runs. A handshake that authenticated just
        # before the revoke checks this right before going live.
        self._revoked: set[str] = set()

    def mark_revoked(self, device_id: str) -> None:
        self._revoked.add(device_id)

    def is_revoked(self, device_id: str) -> bool:
        return device_id in self._revoked

    def current(self, owner_id: str) -> AgentLink | None:
        return self._by_owner.get(owner_id)

    def attach(self, link: AgentLink) -> AgentLink | None:
        """Make `link` the owner's live agent; return the one it replaces, if any."""
        previous = self._by_owner.get(link.owner_id)
        self._by_owner[link.owner_id] = link
        return previous

    def detach(self, link: AgentLink) -> None:
        if self._by_owner.get(link.owner_id) is link:
            del self._by_owner[link.owner_id]

    def status(self, owner_id: str) -> AgentStatus:
        link = self._by_owner.get(owner_id)
        if link is None:
            return AgentStatus(online=False)
        return AgentStatus(
            online=True,
            device_id=link.device_id,
            device_name=link.device_name,
            connected_at=link.connected_at,
            last_heartbeat_at=link.last_heartbeat_at,
        )
