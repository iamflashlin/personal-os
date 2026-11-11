"""Outside sources the Hub syncs in the background (ADR 0019)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.credentials import CredentialName


class IntegrationKind(StrEnum):
    ics = "ics"  # a calendar feed; its URL is the credential (Canvas puts a token in it)


class IntegrationStatus(StrEnum):
    never_synced = "never_synced"
    ok = "ok"
    error = "error"


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: IntegrationKind
    name: Annotated[str, Field(min_length=1, max_length=80)]
    credential_name: CredentialName
    interval_s: Annotated[int, Field(ge=300, le=86400)] = 900


class Integration(BaseModel):
    id: str
    kind: IntegrationKind
    name: str
    credential_name: str
    interval_s: int
    status: IntegrationStatus
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_error: str
    item_count: int
    created_at: datetime
    updated_at: datetime
    version: int


class SyncedItem(BaseModel):
    id: str
    integration_id: str
    item_type: str
    external_id: str
    title: str
    body: str
    location: str
    url: str
    starts_at: datetime | None
    ends_at: datetime | None
    all_day: bool
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int
