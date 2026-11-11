"""model calls

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_call",
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("prompt_name", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prompt_sha", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_kind", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimate_micro_usd", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("finish_reason", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("model_call", schema=None) as batch_op:
        batch_op.create_index(
            "ix_model_call_owner_id_created_at", ["owner_id", "created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_model_call_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("model_call", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_call_owner_id"))
        batch_op.drop_index("ix_model_call_owner_id_created_at")

    op.drop_table("model_call")
