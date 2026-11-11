"""WebSocket protocol between the Hub and the desktop agent (ADR 0014).

The agent opens the connection with `Authorization: Bearer <token>`. Each frame is one
JSON message with a `type` discriminator.
"""

from datetime import UTC, datetime
from enum import IntEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from packages.contracts.actions import ActionName, ActionRequest, ActionResult

PROTOCOL_VERSION = 1
AGENT_WS_PATH = "/agent/ws"


def _now() -> datetime:
    return datetime.now(UTC)


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    msg_id: str = Field(default_factory=lambda: uuid4().hex)
    sent_at: datetime = Field(default_factory=_now)


class Hello(_Msg):
    type: Literal["hello"] = "hello"
    agent_version: Annotated[str, Field(max_length=40)]
    platform: Annotated[str, Field(max_length=20)]
    supported_actions: list[ActionName]


class Heartbeat(_Msg):
    type: Literal["heartbeat"] = "heartbeat"


class ActionResultMsg(_Msg):
    type: Literal["action_result"] = "action_result"
    result: ActionResult


class Welcome(_Msg):
    type: Literal["welcome"] = "welcome"
    device_id: str
    heartbeat_interval_s: float


class HeartbeatAck(_Msg):
    type: Literal["heartbeat_ack"] = "heartbeat_ack"


class ActionRequestMsg(_Msg):
    type: Literal["action_request"] = "action_request"
    request: ActionRequest


AgentToHub = Annotated[Hello | Heartbeat | ActionResultMsg, Field(discriminator="type")]
HubToAgent = Annotated[Welcome | HeartbeatAck | ActionRequestMsg, Field(discriminator="type")]
AGENT_TO_HUB: TypeAdapter[AgentToHub] = TypeAdapter(AgentToHub)
HUB_TO_AGENT: TypeAdapter[HubToAgent] = TypeAdapter(HubToAgent)


class CloseCode(IntEnum):
    protocol_error = 1008
    unauthorized = 4401  # token revoked while connected: the agent stops and must re-pair
    heartbeat_timeout = 4408
    replaced = 4409  # a newer agent connected for this owner: the old one stops
