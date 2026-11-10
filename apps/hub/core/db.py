from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, event

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
DB_FILENAME = "hub.sqlite"


def make_engine(data_dir: Path) -> Engine:
    """Engine for `<data_dir>/hub.sqlite`. The file is created on first connect.

    pysqlite only emits BEGIN before DML, so DDL would autocommit and a failed
    migration would leave a half-built schema. We switch the driver to autocommit and
    emit BEGIN ourselves (SQLAlchemy's documented pysqlite recipe).
    """
    engine = create_engine(f"sqlite:///{(data_dir / DB_FILENAME).as_posix()}")

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("no Alembic revisions found")
    return head


def upgrade_to_head(engine: Engine) -> None:
    cfg = _alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        rev = MigrationContext.configure(conn).get_current_revision()
    if rev is None:
        raise RuntimeError("database has not been migrated")
    return rev
