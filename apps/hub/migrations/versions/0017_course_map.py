"""course knowledge maps and the user's mastery (ADR 0041)

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _common() -> list[sa.Column]:
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
        "course_map",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("material", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("concepts", sa.JSON(), nullable=False),
        sa.Column("exams", sa.JSON(), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False),
        *_common(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "code", name="uq_course_map_owner_id_code"),
    )
    with op.batch_alter_table("course_map", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_course_map_owner_id"), ["owner_id"], unique=False)
    op.create_table(
        "concept_mastery",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=False),
        *_common(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "code", "key", name="uq_concept_mastery_owner_id_code_key"),
    )
    with op.batch_alter_table("concept_mastery", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_concept_mastery_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("concept_mastery", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_concept_mastery_owner_id"))
    op.drop_table("concept_mastery")
    with op.batch_alter_table("course_map", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_course_map_owner_id"))
    op.drop_table("course_map")
