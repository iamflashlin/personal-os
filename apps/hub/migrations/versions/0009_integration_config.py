"""integration config

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("integration", schema=None) as batch_op:
        # Existing integrations get an empty config.
        batch_op.add_column(sa.Column("config", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("integration", schema=None) as batch_op:
        batch_op.drop_column("config")
