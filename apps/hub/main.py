from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.settings import Settings
from apps.hub.system import service as system
from apps.hub.tasks import api as tasks_api
from packages.contracts.health import HealthResponse

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def _allowed_hosts(bind_host: str) -> list[str]:
    """Loopback names, plus the bind address unless it is a wildcard (never a Host header)."""
    hosts = {"127.0.0.1", "localhost"}
    if bind_host not in ("0.0.0.0", "::", ""):
        hosts.add(bind_host)
    return sorted(hosts)


def create_app(settings: Settings | None = None, web_dist: Path | None = WEB_DIST) -> FastAPI:
    """The Hub API; also serves the built web UI at `/` when `web_dist` exists."""
    settings = settings or Settings()
    engine = make_engine(settings.data_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Personal OS Hub", lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    # Rejects requests whose Host is not this machine, so a web page that DNS-rebinds its
    # own domain to 127.0.0.1 cannot drive the API from the user's browser (ADR 0011).
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_allowed_hosts(settings.hub_host),
    )

    @app.get("/health")
    def health() -> HealthResponse:
        return system.get_health(engine)

    app.include_router(tasks_api.build_router())
    if web_dist is not None and (web_dist / "index.html").is_file():
        # Mounted last, so every API route above wins over a same-named static path. A wrong
        # method on an API path therefore falls through to here and gets 404, not 405.
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app
