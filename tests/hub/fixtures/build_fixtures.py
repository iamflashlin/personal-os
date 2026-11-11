"""Rebuild the committed export fixtures.

    uv run python -m tests.hub.fixtures.build_fixtures

export-schema-0001.zip is a package exported from a database migrated only to Alembic
revision 0001 (before the task and audit tables existed). test_backup.py imports it to
prove that an older package is migrated to the current head.
"""

import tempfile
from pathlib import Path

from alembic import command

from apps.hub.backup.service import export_data
from apps.hub.core.db import _alembic_config, make_engine  # pyright: ignore[reportPrivateUsage]

HERE = Path(__file__).resolve().parent
SCHEMA_0001 = HERE / "export-schema-0001.zip"


def build_schema_0001(out: Path = SCHEMA_0001) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        engine = make_engine(data_dir)
        cfg = _alembic_config()
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0001")
        engine.dispose()
        export_data(data_dir, out)


if __name__ == "__main__":
    build_schema_0001()
    print(f"wrote {SCHEMA_0001}")
