"""Run the Hub: `uv run python -m apps.hub` (binds POS_HUB_HOST:POS_HUB_PORT)."""

import uvicorn

from apps.hub.core.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "apps.hub.main:create_app", factory=True, host=settings.hub_host, port=settings.hub_port
    )


if __name__ == "__main__":
    main()
