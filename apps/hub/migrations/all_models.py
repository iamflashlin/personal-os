"""Import every module's ORM models so they register on `Base.metadata`.

Alembic autogenerate and the model/migration drift test only see tables imported here.
"""

from typing import Any

import apps.hub.academic.models
import apps.hub.actions.models
import apps.hub.audit.models
import apps.hub.credentials.models
import apps.hub.devices.models
import apps.hub.digest.models
import apps.hub.evidence.models
import apps.hub.integrations.models
import apps.hub.jobs.models
import apps.hub.memory.models
import apps.hub.models.models
import apps.hub.schedule.models
import apps.hub.summaries.models
import apps.hub.tasks.models
import apps.hub.triage.models  # noqa: F401

# Tables that migrations create with raw SQL and no ORM model: the FTS5 index on
# memory.body (migration 0004) and the shadow tables SQLite keeps for it.
UNMODELLED_TABLE_PREFIXES = ("memory_fts",)


def include_object(
    _obj: Any, name: str | None, type_: str, _reflected: bool, _compare_to: Any
) -> bool:
    """Alembic filter: leave raw-SQL tables out of autogenerate and drift checks."""
    return not (type_ == "table" and (name or "").startswith(UNMODELLED_TABLE_PREFIXES))
