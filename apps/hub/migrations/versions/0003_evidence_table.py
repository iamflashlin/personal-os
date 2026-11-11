"""evidence table

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("task_id", sa.String(length=26), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_evidence_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_evidence_task_id"), ["task_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_task_id"))
        batch_op.drop_index(batch_op.f("ix_evidence_owner_id"))

    op.drop_table("evidence")
