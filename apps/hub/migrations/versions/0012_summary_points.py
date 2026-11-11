"""summary points and low-value flag

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_summary", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("points", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(
            sa.Column("low_value", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("email_summary", schema=None) as batch_op:
        batch_op.drop_column("low_value")
        batch_op.drop_column("points")
