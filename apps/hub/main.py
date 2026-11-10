from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.settings import Settings
from apps.hub.system import service as system
from apps.hub.tasks import api as tasks_api
from packages.contracts.health import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
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

    @app.get("/health")
    def health() -> HealthResponse:
        return system.get_health(engine)

    app.include_router(tasks_api.build_router())
    return app
