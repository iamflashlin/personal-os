"""devices and action runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_disconnected_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("device", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_device_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_device_token_hash"), ["token_hash"], unique=True)

    op.create_table(
        "action_run",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=2), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.String(length=26), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_action_run_owner_id_key"),
    )
    with op.batch_alter_table("action_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_action_run_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_action_run_status"), ["status"], unique=False)

    op.create_table(
        "pairing_code",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("device_id", sa.String(length=26), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pairing_code", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pairing_code_code_hash"), ["code_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_pairing_code_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("pairing_code", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pairing_code_owner_id"))
        batch_op.drop_index(batch_op.f("ix_pairing_code_code_hash"))

    op.drop_table("pairing_code")
    with op.batch_alter_table("action_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_action_run_status"))
        batch_op.drop_index(batch_op.f("ix_action_run_owner_id"))

    op.drop_table("action_run")
    with op.batch_alter_table("device", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_device_token_hash"))
        batch_op.drop_index(batch_op.f("ix_device_owner_id"))

    op.drop_table("device")
