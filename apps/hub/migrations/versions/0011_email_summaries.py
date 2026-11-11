"""email summaries

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_summary",
        sa.Column("item_id", sa.String(length=26), nullable=False),
        sa.Column("item_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("gist", sa.Text(), nullable=False),
        sa.Column("action_needed", sa.Boolean(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("deadline_text", sa.String(length=100), nullable=False),
        sa.Column("deadline_date", sa.Date(), nullable=True),
        sa.Column("importance", sa.String(length=8), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_try_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("model_call_id", sa.String(length=26), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["synced_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "item_id", name="uq_email_summary_owner_id_item_id"),
    )
    with op.batch_alter_table("email_summary", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_email_summary_item_id"), ["item_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_email_summary_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_email_summary_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("email_summary", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_email_summary_status"))
        batch_op.drop_index(batch_op.f("ix_email_summary_item_id"))
        batch_op.drop_index(batch_op.f("ix_email_summary_owner_id"))

    op.drop_table("email_summary")
