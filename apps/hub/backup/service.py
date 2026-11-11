"""Export package layout (format 1):

    manifest.json            format, schema version, row counts, SHA-256 of every file
    db/hub.sqlite            SQLite online backup: what import restores
    tables/<table>.jsonl     every row as JSON, sorted by primary key: readable copy
    files/...                the Hub file directory, if any

Import restores into an empty directory, verifies every checksum and row count, then
migrates the database to the current head. Every failure surfaces as `BackupError` with a
one-line message; the target is never left half-written.
"""

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
import zlib
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError

from apps.hub.core.db import DB_FILENAME, make_engine, upgrade_to_head

FORMAT_VERSION = 1
MANIFEST = "manifest.json"
DB_ENTRY = f"db/{DB_FILENAME}"
FILES_DIR = "files"
TABLES_DIR = "tables"


class BackupError(Exception):
    """The package or the target directory cannot be used; the message says why."""


@dataclass(frozen=True)
class Manifest:
    format_version: int
    schema_version: str
    row_counts: dict[str, int]
    sha256: dict[str, str]

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, data: bytes) -> "Manifest":
        try:
            raw = json.loads(data.decode("utf-8"))
            return cls(
                format_version=int(raw["format_version"]),
                schema_version=str(raw["schema_version"]),
                row_counts={str(k): int(v) for k, v in raw["row_counts"].items()},
                sha256={str(k): str(v) for k, v in raw["sha256"].items()},
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BackupError(f"manifest.json is malformed: {exc}") from exc


@dataclass(frozen=True)
class ImportResult:
    manifest: Manifest
    schema_version: str  # after migration


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$base64": base64.b64encode(value).decode("ascii")}
    return value


def _order_by(conn: sqlite3.Connection, table: str) -> str:
    """Primary-key columns in key order, or rowid for a table without a declared key."""
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    keys = sorted((row[5], row[1]) for row in info if row[5] > 0)
    return ", ".join(f'"{name}"' for _, name in keys) or "rowid"


def table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Every row of `table` as a dict, in primary-key order."""
    cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY {_order_by(conn, table)}')
    names = [d[0] for d in cursor.description]
    return [{n: _json_value(v) for n, v in zip(names, row, strict=True)} for row in cursor]


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tables(conn)}


def _schema_version(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError as exc:
        raise BackupError("database has no alembic_version table") from exc
    if row is None:
        raise BackupError("database has no schema version")
    return str(row[0])


def _safe_entry_name(name: str) -> bool:
    """Plain forward-slash relative paths only: no drive, root, backslash or `..`."""
    parts = name.split("/")
    return (
        bool(name)
        and "\\" not in name
        and ":" not in name
        and not name.startswith("/")
        and all(p not in ("", ".", "..") for p in parts)
    )


# Failures caused by the package, the disk or the database, not by bugs in this module.
# Anything else propagates with its traceback so a defect is not mistaken for a bad package.
_EXPECTED_FAILURES = (
    OSError,
    sqlite3.Error,
    UnicodeDecodeError,
    zipfile.BadZipFile,
    zlib.error,
    SQLAlchemyError,
    CommandError,
)


def _guarded[T](action: str, work: Callable[[], T]) -> T:
    """Run `work`, turning expected low-level failures into a one-line BackupError."""
    try:
        return work()
    except _EXPECTED_FAILURES as exc:
        raise BackupError(f"{action} failed: {type(exc).__name__}: {exc}") from exc


def _retry_on_lock[T](operation: Callable[[], T], attempts: int = 5) -> T:
    """Windows antivirus/indexers briefly hold freshly written files; retry a rename."""
    delay = 0.1
    for attempt in range(attempts):
        try:
            return operation()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def _collect_files(data_dir: Path) -> dict[str, bytes]:
    files_root = data_dir / FILES_DIR
    entries: dict[str, bytes] = {}
    seen_folded: dict[str, str] = {}
    if not files_root.is_dir():
        return entries
    for path in sorted(p for p in files_root.rglob("*") if p.is_file()):
        name = f"{FILES_DIR}/{path.relative_to(files_root).as_posix()}"
        if not _safe_entry_name(name):
            raise BackupError(f"file name cannot be exported portably: {name}")
        folded = name.casefold()
        if folded in seen_folded:
            raise BackupError(f"{name} and {seen_folded[folded]} differ only in letter case")
        seen_folded[folded] = name
        entries[name] = path.read_bytes()
    return entries


def _export(data_dir: Path, out: Path) -> Manifest:
    source = data_dir / DB_FILENAME
    if not source.is_file():
        raise BackupError(f"no Hub database at {source}")

    entries: dict[str, bytes] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    # The snapshot can be as large as the database, so keep it next to `out`, not in %TEMP%.
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        snapshot = Path(tmp) / DB_FILENAME
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(snapshot)) as conn:
            schema_version = _schema_version(conn)
            row_counts: dict[str, int] = {}
            for table in _tables(conn):
                rows = table_rows(conn, table)
                row_counts[table] = len(rows)
                entries[f"{TABLES_DIR}/{table}.jsonl"] = "".join(
                    json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows
                ).encode("utf-8")
        entries[DB_ENTRY] = snapshot.read_bytes()
    entries.update(_collect_files(data_dir))

    manifest = Manifest(
        format_version=FORMAT_VERSION,
        schema_version=schema_version,
        row_counts=row_counts,
        sha256={name: _sha256(data) for name, data in sorted(entries.items())},
    )
    partial = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST, manifest.to_json())
            for name, data in sorted(entries.items()):
                zf.writestr(name, data)
        _retry_on_lock(lambda: os.replace(partial, out))
    finally:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
    return manifest


def export_data(data_dir: Path, out: Path) -> Manifest:
    """Write a package for `data_dir` to `out` (atomically). Safe while the Hub runs."""
    return _guarded("export", lambda: _export(data_dir, out))


def _read_verified(package: Path) -> tuple[Manifest, dict[str, bytes]]:
    with zipfile.ZipFile(package) as zf:
        names = set(zf.namelist())
        if MANIFEST not in names:
            raise BackupError("package has no manifest.json")
        manifest = Manifest.from_json(zf.read(MANIFEST))
        if manifest.format_version != FORMAT_VERSION:
            raise BackupError(f"unsupported package format {manifest.format_version}")
        unlisted = names - set(manifest.sha256) - {MANIFEST}
        if unlisted:
            raise BackupError(f"package contains files not in the manifest: {sorted(unlisted)}")
        entries: dict[str, bytes] = {}
        for name, expected in manifest.sha256.items():
            if not _safe_entry_name(name):
                raise BackupError(f"unsafe path in package: {name}")
            if name != DB_ENTRY and name.split("/", 1)[0] not in (TABLES_DIR, FILES_DIR):
                raise BackupError(f"unexpected entry in package: {name}")
            if name not in names:
                raise BackupError(f"package is missing {name}")
            data = zf.read(name)
            if _sha256(data) != expected:
                raise BackupError(f"checksum mismatch for {name}; the package was altered")
            entries[name] = data
    if DB_ENTRY not in entries:
        raise BackupError(f"package has no {DB_ENTRY}")
    missing_tables = [t for t in manifest.row_counts if f"{TABLES_DIR}/{t}.jsonl" not in entries]
    if missing_tables:
        raise BackupError(f"package has no JSONL copy of: {missing_tables}")
    return manifest, entries


def _restore_into(staging: Path, manifest: Manifest, entries: dict[str, bytes]) -> str:
    root = staging.resolve()
    for name, data in entries.items():
        if name == DB_ENTRY:
            target = staging / DB_FILENAME
        elif name.startswith(f"{FILES_DIR}/"):
            target = staging / name
        else:
            continue
        if not target.resolve().is_relative_to(root):
            raise BackupError(f"unsafe path in package: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    with closing(sqlite3.connect(staging / DB_FILENAME)) as conn:
        (integrity,) = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity != "ok":
            raise BackupError(f"database in package is damaged: {integrity}")
        counts = _row_counts(conn)
    if counts != manifest.row_counts:
        raise BackupError(f"row counts differ from manifest: {counts} != {manifest.row_counts}")

    engine = make_engine(staging)
    try:
        upgrade_to_head(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(staging / DB_FILENAME)) as conn:
        return _schema_version(conn)


def _import(package: Path, data_dir: Path) -> ImportResult:
    if data_dir.exists() and not data_dir.is_dir():
        raise BackupError(f"target {data_dir} exists and is not a directory")
    if data_dir.exists() and any(data_dir.iterdir()):
        raise BackupError(f"target {data_dir} is not empty; import only into an empty directory")
    manifest, entries = _read_verified(package)

    data_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{data_dir.name}.importing-", dir=data_dir.parent))
    existed = data_dir.exists()
    try:
        schema_version = _restore_into(staging, manifest, entries)
        if existed:
            data_dir.rmdir()
        try:
            _retry_on_lock(lambda: staging.rename(data_dir))
        except OSError:
            if existed:
                data_dir.mkdir(exist_ok=True)
            raise
    finally:
        # Best effort: a cleanup failure must not hide the error that got us here.
        shutil.rmtree(staging, ignore_errors=True)
    return ImportResult(manifest, schema_version)


def import_data(package: Path, data_dir: Path) -> ImportResult:
    """Restore `package` into `data_dir`, which must be empty or absent.

    Everything is written to a staging directory next to `data_dir` and moved into place
    only after checksums, integrity, row counts and migrations succeed.
    """
    return _guarded("import", lambda: _import(package, data_dir))
