from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.hub.actions import api as actions_api
from apps.hub.actions import service as actions
from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import api as credentials_api
from apps.hub.credentials import service as credentials
from apps.hub.devices import api as devices_api
from apps.hub.devices import service as devices
from apps.hub.integrations import api as integrations_api
from apps.hub.integrations import service as integrations
from apps.hub.jobs import api as jobs_api
from apps.hub.jobs import service as jobs
from apps.hub.jobs.worker import JobWorker
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


def job_kinds(
    store: credentials.SecretStore | None = None, owner_id: str = "local"
) -> jobs.JobKinds:
    """Every background job kind the Hub knows. Modules add theirs here (ADR 0017).

    Integration syncs need the secret store; without one they are not registered.
    """
    kinds = jobs.JobKinds()
    kinds.register("system.noop", lambda _engine, _job: None)
    if store is not None:
        actor = Actor(owner_id=owner_id, source="jobs")
        kinds.register_family(
            integrations.SYNC_JOB,
            lambda engine, job: integrations.run_sync_job(
                engine, store, actor, job.payload, datetime.now(UTC)
            ),
        )
    return kinds


def create_app(
    settings: Settings | None = None,
    web_dist: Path | None = WEB_DIST,
    kinds: jobs.JobKinds | None = None,
    secret_store: credentials.SecretStore | None = None,
) -> FastAPI:
    """The Hub API; also serves the built web UI at `/` when `web_dist` exists."""
    settings = settings or Settings()
    engine = make_engine(settings.data_dir)
    store = secret_store or credentials.KeyringSecretStore(settings.credentials_service)
    worker = JobWorker(
        engine,
        settings.owner_id,
        kinds or job_kinds(store, settings.owner_id),
        poll_s=settings.jobs_poll_s,
        retry_base=timedelta(seconds=settings.jobs_retry_base_s),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(engine)
        hub = Actor(owner_id=settings.owner_id, source="hub")
        with Session(engine) as session:
            actions.mark_orphans_lost(session, hub)
            retry_base = timedelta(seconds=settings.jobs_retry_base_s)
            jobs.requeue_interrupted(session, hub, datetime.now(UTC), retry_base)
            integrations.ensure_schedules(session, hub, datetime.now(UTC))
        if settings.jobs_enabled:
            worker.start()
        try:
            yield
        finally:
            await worker.stop()
            engine.dispose()

    app = FastAPI(title="Personal OS Hub", lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    app.state.agent_links = devices.AgentLinks()
    app.state.job_worker = worker
    app.state.secret_store = store
    # Rejects requests whose Host is not this machine, so a web page that DNS-rebinds its
    # own domain to 127.0.0.1 cannot drive the API from the user's browser (ADR 0011).
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_allowed_hosts(settings.hub_host),
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default echoes each bad value back ("input"). That would return a
        # mistyped or oversized secret to the caller, who might then log or show it.
        errors = [
            {k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

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
    app.include_router(jobs_api.build_router())
    app.include_router(credentials_api.build_router())
    app.include_router(integrations_api.build_router())
    if web_dist is not None and (web_dist / "index.html").is_file():
        # Mounted last, so every API route above wins over a same-named static path. A wrong
        # method on an API path therefore falls through to here and gets 404, not 405.
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app
