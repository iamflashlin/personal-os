from sqlalchemy import Engine

from apps.hub.core.db import current_revision
from packages.contracts.health import HealthResponse


def get_health(engine: Engine) -> HealthResponse:
    return HealthResponse(status="ok", schema_version=current_revision(engine))
