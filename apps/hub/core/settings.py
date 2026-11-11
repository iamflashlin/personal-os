from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Hub configuration, read from `POS_*` environment variables only (ADR 0008)."""

    model_config = SettingsConfigDict(env_prefix="POS_", frozen=True)

    data_dir: Path = REPO_ROOT / "data"
    hub_host: str = "127.0.0.1"
    hub_port: int = 8765
    owner_id: str = "local"
    agent_heartbeat_s: float = 15.0
    jobs_enabled: bool = True
    jobs_poll_s: Annotated[float, Field(gt=0)] = 1.0
    jobs_retry_base_s: Annotated[float, Field(gt=0)] = 5.0
