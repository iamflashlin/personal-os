"""course profiles from the syllabi (ADR 0040)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_profile",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("term", sa.String(length=40), nullable=False),
        sa.Column("units", sa.Float(), nullable=True),
        sa.Column("units_source", sa.String(length=300), nullable=False),
        sa.Column("scale", sa.JSON(), nullable=False),
        sa.Column("scale_source", sa.String(length=300), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("open_questions", sa.JSON(), nullable=False),
        sa.Column("syllabus_source", sa.String(length=300), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "code", name="uq_course_profile_owner_id_code"),
    )
    with op.batch_alter_table("course_profile", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_course_profile_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("course_profile", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_course_profile_owner_id"))
    op.drop_table("course_profile")
