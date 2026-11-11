"""Agent settings: command-line flags over `POS_AGENT_*` environment variables."""

import os
import platform
from dataclasses import dataclass
from typing import Literal

from packages.contracts.agent_protocol import AGENT_WS_PATH

DEFAULT_HUB_URL = "http://127.0.0.1:8765"
DEFAULT_KEYRING_SERVICE = "personal-os-agent"
AGENT_VERSION = "0.1.0"

Platform = Literal["windows", "macos", "linux"]


def this_platform() -> Platform:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    return "linux"


@dataclass(frozen=True)
class AgentConfig:
    hub_url: str = DEFAULT_HUB_URL
    keyring_service: str = DEFAULT_KEYRING_SERVICE
    device_name: str = platform.node() or "desktop"
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 30.0

    @classmethod
    def from_env(
        cls,
        hub_url: str | None = None,
        keyring_service: str | None = None,
        device_name: str | None = None,
    ) -> "AgentConfig":
        """Each value: the flag if given, else its POS_AGENT_* variable, else the default."""
        default = cls()
        env = os.environ.get
        return cls(
            hub_url=hub_url or env("POS_AGENT_HUB_URL") or default.hub_url,
            keyring_service=keyring_service
            or env("POS_AGENT_KEYRING_SERVICE")
            or default.keyring_service,
            device_name=device_name or env("POS_AGENT_DEVICE_NAME") or default.device_name,
        )

    @property
    def ws_url(self) -> str:
        base = self.hub_url.rstrip("/")
        if base.startswith("https://"):
            return "wss://" + base.removeprefix("https://") + AGENT_WS_PATH
        return "ws://" + base.removeprefix("http://") + AGENT_WS_PATH
