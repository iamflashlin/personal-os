"""tasks and audit tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=26), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_event_entity_id"), ["entity_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_event_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "goal",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("goal", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_goal_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "idempotency_key",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=26), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "key", name="uq_idempotency_key_owner_id_key"),
    )
    with op.batch_alter_table("idempotency_key", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_idempotency_key_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "project",
        sa.Column("goal_id", sa.String(length=26), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goal.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_project_goal_id"), ["goal_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_project_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "task",
        sa.Column("project_id", sa.String(length=26), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_task_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_task_project_id"), ["project_id"], unique=False)

    op.create_table(
        "workspace",
        sa.Column("project_id", sa.String(length=26), nullable=True),
        sa.Column("task_id", sa.String(length=26), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("urls", sa.JSON(), nullable=False),
        sa.Column("folders", sa.JSON(), nullable=False),
        sa.Column("apps", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workspace", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workspace_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workspace_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workspace_task_id"), ["task_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("workspace", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspace_task_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_project_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_owner_id"))

    op.drop_table("workspace")
    with op.batch_alter_table("task", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_task_project_id"))
        batch_op.drop_index(batch_op.f("ix_task_owner_id"))

    op.drop_table("task")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_project_owner_id"))
        batch_op.drop_index(batch_op.f("ix_project_goal_id"))

    op.drop_table("project")
    with op.batch_alter_table("idempotency_key", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_idempotency_key_owner_id"))

    op.drop_table("idempotency_key")
    with op.batch_alter_table("goal", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_goal_owner_id"))

    op.drop_table("goal")
    with op.batch_alter_table("audit_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_event_owner_id"))
        batch_op.drop_index(batch_op.f("ix_audit_event_entity_id"))

    op.drop_table("audit_event")
