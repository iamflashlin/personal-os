"""Integration secrets (HANDOFF §4.6, ADR 0018).

The Hub stores a secret in Windows Credential Manager and keeps only its name and dates
in SQLite. No HTTP route ever returns a secret.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

CREDENTIAL_NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,79}$"
# Windows Credential Manager holds at most 2560 bytes per secret, and keyring stores
# text as UTF-16: 1280 ordinary characters (ADR 0018).
MAX_SECRET_UTF16_BYTES = 2560
CredentialName = Annotated[str, Field(pattern=CREDENTIAL_NAME_PATTERN)]


class CredentialPut(BaseModel):
    """Body of PUT /credentials/{name}. SecretStr keeps the value out of reprs and logs."""

    model_config = ConfigDict(extra="forbid")

    secret: Annotated[SecretStr, Field(min_length=1)]
    note: Annotated[str, Field(max_length=200)] = ""

    @field_validator("secret")
    @classmethod
    def _fits_credential_manager(cls, secret: SecretStr) -> SecretStr:
        if len(secret.get_secret_value().encode("utf-16-le")) > MAX_SECRET_UTF16_BYTES:
            raise ValueError("too long for Windows Credential Manager (about 1280 characters)")
        return secret


class Credential(BaseModel):
    """What the Hub tells about a credential: never the secret itself."""

    id: str
    name: str
    note: str
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
