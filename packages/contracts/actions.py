"""Desktop actions: the whitelist, their risk, and the request/result shapes (HANDOFF §4.2).

Every action the desktop agent may run is listed in ACTION_SPECS. Anything else is
refused before it reaches a PC. P2 and above need a Grant (S8) and are refused until then.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator


class RiskLevel(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


AUTO_APPROVED_RISKS = frozenset({RiskLevel.P0, RiskLevel.P1})


class ActionName(StrEnum):
    open_url = "open_url"
    open_folder_in_editor = "open_folder_in_editor"


class ActionStatus(StrEnum):
    """What the agent reports."""

    succeeded = "succeeded"
    failed = "failed"
    needs_user = "needs_user"
    cancelled = "cancelled"


class ActionRunStatus(StrEnum):
    """What the Hub stores. `lost`: sent, but no result came back; never resent."""

    dispatched = "dispatched"
    succeeded = "succeeded"
    failed = "failed"
    needs_user = "needs_user"
    cancelled = "cancelled"
    lost = "lost"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


TITLE_MAX = 200
Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]


class OpenUrlParams(_Strict):
    url: AnyUrl
    expect_title_contains: Title

    @field_validator("url")
    @classmethod
    def _http_only(cls, url: AnyUrl) -> AnyUrl:
        # file:, javascript:, ms-settings: and friends would let a URL run local things.
        if url.scheme not in ("http", "https"):
            raise ValueError("only http and https URLs can be opened")
        return url


_CMD_METACHARACTERS = frozenset('&|<>^"%!`\r\n\t\0')


class OpenFolderParams(_Strict):
    path: Annotated[str, Field(min_length=3, max_length=260)]

    @field_validator("path")
    @classmethod
    def _absolute(cls, path: str) -> str:
        if not (PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()):
            raise ValueError("the folder path must be absolute")
        # \\host\share and \\?\ paths could make Windows reach out over SMB.
        if path.startswith(("\\", "//")):
            raise ValueError("network and device paths cannot be opened")
        # `code` is a .cmd script on Windows, so cmd.exe re-parses its arguments.
        if any(c in _CMD_METACHARACTERS for c in path):
            raise ValueError("the folder path contains a character cmd.exe would interpret")
        return path


class ActionEvidenceKind(StrEnum):
    window = "window"
    note = "note"


class EvidenceItem(_Strict):
    kind: ActionEvidenceKind
    summary: Annotated[str, Field(max_length=500)]
    data: dict[str, str | int | bool] = Field(default_factory=dict[str, str | int | bool])
    captured_at: datetime


@dataclass(frozen=True)
class ActionSpec:
    name: ActionName
    params: type[BaseModel]
    risk: RiskLevel
    reversible: bool
    timeout_s: float


ACTION_SPECS: Mapping[ActionName, ActionSpec] = MappingProxyType(
    {
        ActionName.open_url: ActionSpec(
            ActionName.open_url, OpenUrlParams, RiskLevel.P1, True, 20.0
        ),
        ActionName.open_folder_in_editor: ActionSpec(
            ActionName.open_folder_in_editor, OpenFolderParams, RiskLevel.P1, True, 30.0
        ),
    }
)


def parse_params(name: ActionName, params: dict[str, Any]) -> BaseModel:
    """Validate params for `name`; raises pydantic.ValidationError."""
    return ACTION_SPECS[name].params.model_validate(params)


class ActionCreate(_Strict):
    """Body of POST /actions."""

    name: ActionName
    params: dict[str, Any]


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=200)]
Ulid = Annotated[str, Field(min_length=26, max_length=26)]


class ActionRequest(_Strict):
    """Hub -> agent."""

    action_id: Ulid
    idempotency_key: IdempotencyKey
    name: ActionName
    params: dict[str, Any]
    risk_level: RiskLevel
    timeout_s: Annotated[float, Field(gt=0, le=120)]
    issued_at: datetime


class ActionResult(_Strict):
    """Agent -> Hub."""

    action_id: Ulid
    idempotency_key: IdempotencyKey
    status: ActionStatus
    message: Annotated[str, Field(max_length=2000)] = ""
    evidence: Annotated[list[EvidenceItem], Field(max_length=20)] = Field(
        default_factory=list[EvidenceItem]
    )
    started_at: datetime
    finished_at: datetime
    replayed: bool = False


class ActionRun(BaseModel):
    """What the Hub stored for one dispatched action."""

    id: str
    name: ActionName
    params: dict[str, Any]
    risk_level: RiskLevel
    idempotency_key: str
    status: ActionRunStatus
    device_id: str | None
    message: str
    evidence: list[EvidenceItem]
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
