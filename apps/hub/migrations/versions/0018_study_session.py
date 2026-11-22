"""study sessions for 开始学习 (ADR 0042)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_session",
        sa.Column("course_code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_study_session_owner_id_idempotency_key"
        ),
    )
    with op.batch_alter_table("study_session", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_study_session_course_code"), ["course_code"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_study_session_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("study_session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_study_session_owner_id"))
        batch_op.drop_index(batch_op.f("ix_study_session_course_code"))
    op.drop_table("study_session")
