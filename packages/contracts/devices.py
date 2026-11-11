"""Pairing a desktop agent with the Hub (HANDOFF §4.5)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Crockford base32 without I, L, O, U: 8 characters, 40 bits, optional dash in the middle.
PAIRING_CODE_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{4}-?[0-9A-HJKMNP-TV-Z]{4}$"
# Every agent token starts with this, so log redaction can recognise it.
TOKEN_PREFIX = "posd_"


class PairingCode(BaseModel):
    """Shown to the user once; the Hub keeps only its hash."""

    code: str
    expires_at: datetime


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(pattern=PAIRING_CODE_PATTERN)]
    device_name: Annotated[str, Field(min_length=1, max_length=80)]
    platform: Literal["windows", "macos", "linux"]

    @field_validator("code", mode="before")
    @classmethod
    def _normalise(cls, code: object) -> object:
        return code.strip().upper() if isinstance(code, str) else code


class PairResponse(BaseModel):
    """The token is returned exactly once and never stored by the Hub."""

    device_id: str
    token: str


class Device(BaseModel):
    id: str
    name: str
    platform: str
    created_at: datetime
    revoked_at: datetime | None
    last_connected_at: datetime | None
    last_disconnected_at: datetime | None
    version: int


class AgentStatus(BaseModel):
    online: bool
    device_id: str | None = None
    device_name: str | None = None
    connected_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
