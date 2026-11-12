"""digest items for the 简报 (ADR 0039)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "digest_item",
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("happens_at", sa.DateTime(), nullable=True),
        sa.Column("important", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "dedup_key", name="uq_digest_item_owner_id_dedup_key"),
    )
    with op.batch_alter_table("digest_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_digest_item_channel"), ["channel"], unique=False)
        batch_op.create_index(batch_op.f("ix_digest_item_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_digest_item_published_at"), ["published_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("digest_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_digest_item_published_at"))
        batch_op.drop_index(batch_op.f("ix_digest_item_owner_id"))
        batch_op.drop_index(batch_op.f("ix_digest_item_channel"))
    op.drop_table("digest_item")
