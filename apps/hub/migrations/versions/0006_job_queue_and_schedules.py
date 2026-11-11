"""job queue and schedules

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_job_owner_id_key"),
    )
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_job_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_job_run_at"), ["run_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_job_status"), ["status"], unique=False)

    op.create_table(
        "job_schedule",
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "kind", name="uq_job_schedule_owner_id_kind"),
    )
    with op.batch_alter_table("job_schedule", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_schedule_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_schedule", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_schedule_owner_id"))

    op.drop_table("job_schedule")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_status"))
        batch_op.drop_index(batch_op.f("ix_job_run_at"))
        batch_op.drop_index(batch_op.f("ix_job_owner_id"))
        batch_op.drop_index(batch_op.f("ix_job_kind"))

    op.drop_table("job")
