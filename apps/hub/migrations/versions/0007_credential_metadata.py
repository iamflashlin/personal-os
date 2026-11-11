"""credential metadata

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_credential_owner_id_name"),
    )
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_credential_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_credential_owner_id"))

    op.drop_table("credential")
