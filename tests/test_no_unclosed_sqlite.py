"""Guard for docs/lessons.md (2026-11-10): `with sqlite3.connect(...)` does not close."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("apps", "packages", "scripts", "tests", "tools")
UNCLOSED = re.compile(r"with\s+sqlite3\.connect\(")


def test_sqlite_connections_are_closed_explicitly() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{number}"
        for folder in SCANNED
        for path in sorted((ROOT / folder).rglob("*.py"))
        if "node_modules" not in path.parts and path != Path(__file__).resolve()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if UNCLOSED.search(line)
    ]
    assert offenders == [], (
        "`with sqlite3.connect(...)` commits but never closes the connection, which locks "
        f"the file on Windows; use `with closing(sqlite3.connect(...))` instead: {offenders}"
    )
