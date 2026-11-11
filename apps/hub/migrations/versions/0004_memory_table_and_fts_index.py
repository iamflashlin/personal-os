"""memory table and fts index

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provenance", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memory", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memory_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_owner_id"), ["owner_id"], unique=False)

    # Full-text index on memory.body. `trigram` matches substrings in any language, which
    # `unicode61` cannot do for Chinese (ADR 0013). External content: the index stores no
    # copy of the text; the triggers keep it in step with every insert, update and delete.
    op.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5("
        "body, content='memory', content_rowid='rowid', tokenize='trigram')"
    )
    op.execute(
        "CREATE TRIGGER memory_fts_ai AFTER INSERT ON memory BEGIN "
        "INSERT INTO memory_fts(rowid, body) VALUES (new.rowid, new.body); END"
    )
    op.execute(
        "CREATE TRIGGER memory_fts_ad AFTER DELETE ON memory BEGIN "
        "INSERT INTO memory_fts(memory_fts, rowid, body) VALUES ('delete', old.rowid, old.body);"
        " END"
    )
    op.execute(
        "CREATE TRIGGER memory_fts_au AFTER UPDATE OF body ON memory BEGIN "
        "INSERT INTO memory_fts(memory_fts, rowid, body) VALUES ('delete', old.rowid, old.body);"
        " INSERT INTO memory_fts(rowid, body) VALUES (new.rowid, new.body); END"
    )


def downgrade() -> None:
    for trigger in ("memory_fts_au", "memory_fts_ad", "memory_fts_ai"):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS memory_fts")
    with op.batch_alter_table("memory", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_owner_id"))
        batch_op.drop_index(batch_op.f("ix_memory_kind"))
        batch_op.drop_index(batch_op.f("ix_memory_expires_at"))

    op.drop_table("memory")
