from pathlib import Path

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
