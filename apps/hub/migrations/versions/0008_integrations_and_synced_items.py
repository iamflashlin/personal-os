"""integrations and synced items

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("credential_name", sa.String(length=80), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("cursor", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("integration", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_integration_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "synced_item",
        sa.Column("integration_id", sa.String(length=26), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["integration.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id", "item_type", "external_id", name="uq_synced_item_source_id"
        ),
    )
    with op.batch_alter_table("synced_item", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_synced_item_integration_id"), ["integration_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_synced_item_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_synced_item_starts_at"), ["starts_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("synced_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_synced_item_starts_at"))
        batch_op.drop_index(batch_op.f("ix_synced_item_owner_id"))
        batch_op.drop_index(batch_op.f("ix_synced_item_integration_id"))

    op.drop_table("synced_item")
    with op.batch_alter_table("integration", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_owner_id"))

    op.drop_table("integration")
