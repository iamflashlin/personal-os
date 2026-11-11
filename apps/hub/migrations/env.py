from alembic import context

from apps.hub.core.base import Base
from apps.hub.migrations.all_models import include_object

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,
    include_object=include_object,
)
with context.begin_transaction():
    context.run_migrations()
