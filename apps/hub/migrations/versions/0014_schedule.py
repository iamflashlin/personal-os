"""schedule events (ADR 0038)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_event",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("repeat_days", sa.JSON(), nullable=False),
        sa.Column("repeat_until", sa.Date(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("schedule_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_schedule_event_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_schedule_event_starts_at"), ["starts_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("schedule_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_schedule_event_starts_at"))
        batch_op.drop_index(batch_op.f("ix_schedule_event_owner_id"))
    op.drop_table("schedule_event")
