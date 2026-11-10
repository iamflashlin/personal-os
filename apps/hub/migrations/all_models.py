"""Import every module's ORM models so they register on `Base.metadata`.

Alembic autogenerate and the model/migration drift test only see tables imported here.
"""

import apps.hub.audit.models
import apps.hub.tasks.models  # noqa: F401
