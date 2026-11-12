"""mail triage: in-app handled state, batches, rules (ADR 0034)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _entity() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "triage_batch",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("group_key", sa.String(length=120), nullable=False),
        sa.Column("applied_ids", sa.JSON(), nullable=False),
        sa.Column("rule_id", sa.String(length=26), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        *_entity(),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("triage_batch", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_triage_batch_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index("ix_triage_batch_owner_status", ["owner_id", "status"], unique=False)

    op.create_table(
        "mail_triage_state",
        sa.Column("item_id", sa.String(length=26), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("prev_state", sa.String(length=12), nullable=False),
        sa.Column("batch_id", sa.String(length=26), nullable=True),
        *_entity(),
        sa.ForeignKeyConstraint(["item_id"], ["synced_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "item_id", name="uq_mail_triage_state_owner_id_item_id"),
    )
    with op.batch_alter_table("mail_triage_state", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_mail_triage_state_batch_id"), ["batch_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_mail_triage_state_item_id"), ["item_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_mail_triage_state_owner_id"), ["owner_id"], unique=False
        )

    op.create_table(
        "triage_rule",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("selector", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("from_batch_id", sa.String(length=26), nullable=True),
        *_entity(),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("triage_rule", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_triage_rule_enabled"), ["enabled"], unique=False)
        batch_op.create_index(batch_op.f("ix_triage_rule_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("triage_rule", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_triage_rule_owner_id"))
        batch_op.drop_index(batch_op.f("ix_triage_rule_enabled"))
    op.drop_table("triage_rule")
    with op.batch_alter_table("mail_triage_state", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mail_triage_state_owner_id"))
        batch_op.drop_index(batch_op.f("ix_mail_triage_state_item_id"))
        batch_op.drop_index(batch_op.f("ix_mail_triage_state_batch_id"))
    op.drop_table("mail_triage_state")
    with op.batch_alter_table("triage_batch", schema=None) as batch_op:
        batch_op.drop_index("ix_triage_batch_owner_status")
        batch_op.drop_index(batch_op.f("ix_triage_batch_owner_id"))
    op.drop_table("triage_batch")
