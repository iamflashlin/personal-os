import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.orm.exc import StaleDataError

import apps.hub.migrations.all_models  # noqa: F401
from apps.hub.core.base import Base, Entity
from apps.hub.core.db import DB_FILENAME, head_revision, make_engine
from apps.hub.core.settings import Settings
from tests.hub.support import hub_client


def test_fresh_data_dir_is_migrated_to_head_on_startup(client: TestClient, data_dir: Path) -> None:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        (rev,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert rev == head_revision()


def test_database_uses_wal(client: TestClient, data_dir: Path) -> None:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode == "wal"


def test_health_reports_ok_and_schema_head(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": head_revision()}


def test_restart_on_existing_data_dir_keeps_working(data_dir: Path) -> None:
    for _ in range(2):
        with hub_client(Settings(data_dir=data_dir)) as c:
            assert c.get("/health").json()["schema_version"] == head_revision()


def test_hub_defaults_to_loopback_and_ignores_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POS_HUB_HOST", raising=False)
    assert Settings().hub_host == "127.0.0.1"
    assert Settings.model_config.get("env_file") is None


def test_failed_migration_leaves_no_partial_schema(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with pytest.raises(RuntimeError), engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE half_built (a INTEGER)")
        raise RuntimeError("migration step failed")
    assert "half_built" not in inspect(engine).get_table_names()
    engine.dispose()


def test_migrations_match_the_models(client: TestClient) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    assert diff == [], "run autogenerate: models and migrations differ"


class _TestBase(DeclarativeBase):
    pass


class Thing(Entity, _TestBase):
    __tablename__ = "thing"


@pytest.fixture
def session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 't.sqlite').as_posix()}")
    _TestBase.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_entity_mixin_fills_common_columns(session: Session) -> None:
    thing = Thing(owner_id="owner-1", source="test")
    session.add(thing)
    session.commit()
    session.expire_all()

    loaded = session.get_one(Thing, thing.id)
    assert len(loaded.id) == 26
    assert loaded.owner_id == "owner-1"
    assert loaded.source == "test"
    assert loaded.version == 1
    assert loaded.created_at.tzinfo is UTC
    assert loaded.updated_at.tzinfo is UTC
    assert abs(loaded.created_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_ulids_sort_by_creation(session: Session) -> None:
    things = [Thing(owner_id="o", source="test") for _ in range(3)]
    for t in things:
        session.add(t)
        session.flush()
    assert [t.id for t in things] == sorted(t.id for t in things)


def test_update_bumps_version_and_updated_at(session: Session) -> None:
    thing = Thing(owner_id="o", source="test")
    session.add(thing)
    session.commit()
    first_updated = thing.updated_at

    thing.source = "changed"
    session.commit()
    assert thing.version == 2
    assert thing.updated_at >= first_updated


def test_stale_version_update_is_rejected(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 't.sqlite').as_posix()}")
    _TestBase.metadata.create_all(engine)
    with Session(engine) as a, Session(engine) as b:
        thing = Thing(owner_id="o", source="test")
        a.add(thing)
        a.commit()
        stale = b.get_one(Thing, thing.id)

        thing.source = "a"
        a.commit()
        stale.source = "b"
        with pytest.raises(StaleDataError):
            b.commit()
    engine.dispose()


def test_non_utc_timestamps_are_normalised(session: Session) -> None:
    plus8 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    thing = Thing(owner_id="o", source="test", created_at=plus8)
    session.add(thing)
    session.commit()
    session.expire_all()
    assert session.get_one(Thing, thing.id).created_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_naive_timestamps_are_rejected(session: Session) -> None:
    session.add(Thing(owner_id="o", source="test", created_at=datetime(2026, 1, 1)))
    with pytest.raises(StatementError, match="naive datetime"):
        session.commit()
