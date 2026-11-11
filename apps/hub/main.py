from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.hub.actions import api as actions_api
from apps.hub.actions import service as actions
from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.devices import api as devices_api
from apps.hub.devices import service as devices
from apps.hub.memory import api as memory_api
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
        with Session(engine) as session:
            actions.mark_orphans_lost(session, Actor(owner_id=settings.owner_id, source="hub"))
        yield
        engine.dispose()

    app = FastAPI(title="Personal OS Hub", lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    app.state.agent_links = devices.AgentLinks()
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
    app.include_router(memory_api.build_router())
    app.include_router(
        devices_api.build_router(
            devices.AgentHooks(on_result=actions.record_result, on_lost=actions.mark_lost)
        )
    )
    app.include_router(actions_api.build_router())
    if web_dist is not None and (web_dist / "index.html").is_file():
        # Mounted last, so every API route above wins over a same-named static path. A wrong
        # method on an API path therefore falls through to here and gets 404, not 405.
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app
