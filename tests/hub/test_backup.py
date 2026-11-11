import hashlib
import json
import sqlite3
import sys
import threading
import time
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.hub.backup import service as backup_service
from apps.hub.backup.service import (
    MANIFEST,
    BackupError,
    Manifest,
    _safe_entry_name,  # pyright: ignore[reportPrivateUsage]
    export_data,
    import_data,
    table_rows,
)
from apps.hub.core.db import DB_FILENAME, head_revision
from apps.hub.core.settings import Settings
from tests.hub.support import hub_client
from tools.pos import main as pos

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA_0001_PACKAGE = FIXTURES / "export-schema-0001.zip"
COLLECTIONS = ("goals", "projects", "tasks", "workspaces")


def dump(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    with closing(sqlite3.connect(data_dir / DB_FILENAME)) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        result = {t: table_rows(conn, t) for t in sorted(tables)}
    return result


def seed(client: TestClient) -> None:
    goal = client.post("/goals", json={"title": "Pass CIS"}).json()
    project = client.post("/projects", json={"title": "Lab 3", "goal_id": goal["id"]}).json()
    first = client.post(
        "/tasks",
        json={"title": "Read handout", "project_id": project["id"], "tags": ["course:CIS"]},
        headers={"Idempotency-Key": "seed-1"},
    ).json()
    client.post("/tasks", json={"title": "Write notes", "depends_on": [first["id"]]})
    client.post("/workspaces", json={"title": "Desk", "task_id": first["id"], "urls": ["x"]})
    client.patch(f"/goals/{goal['id']}", json={"version": 1, "title": "Pass CIS 101"})


def test_round_trip_keeps_every_row_identical(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    seed(client)
    files = {
        "notes/lab 3.txt": "实验三的笔记\n".encode(),
        "attachments/scan.bin": bytes(range(256)) * 4,
    }
    for name, data in files.items():
        (data_dir / "files" / name).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / "files" / name).write_bytes(data)
    package = tmp_path / "export.zip"
    manifest = export_data(data_dir, package)
    assert {f"files/{n}" for n in files} <= set(manifest.sha256)
    assert manifest.schema_version == head_revision()
    assert manifest.row_counts["audit_event"] == 6
    assert manifest.row_counts["task"] == 2
    before = dump(data_dir)
    api_before = {k: client.get(f"/{k}").json() for k in COLLECTIONS}

    with zipfile.ZipFile(package) as zf:
        for table, rows in before.items():
            lines = zf.read(f"tables/{table}.jsonl").decode("utf-8").splitlines()
            assert [json.loads(line) for line in lines] == rows, f"JSONL copy of {table}"

    restored = tmp_path / "restored"
    result = import_data(package, restored)
    assert result.schema_version == head_revision()

    with hub_client(Settings(data_dir=restored)) as again:
        assert again.get("/health").json() == {"status": "ok", "schema_version": head_revision()}
        assert {k: again.get(f"/{k}").json() for k in COLLECTIONS} == api_before
        assert again.get("/goals").json()[0]["version"] == 2
    assert dump(restored) == before
    for name, data in files.items():
        assert (restored / "files" / name).read_bytes() == data, name


def test_package_lists_a_checksum_for_every_entry(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    seed(client)
    package = tmp_path / "export.zip"
    export_data(data_dir, package)
    with zipfile.ZipFile(package) as zf:
        manifest = Manifest.from_json(zf.read(MANIFEST))
        assert set(zf.namelist()) == set(manifest.sha256) | {MANIFEST}
    assert "db/hub.sqlite" in manifest.sha256
    assert "tables/goal.jsonl" in manifest.sha256


def _rewrite(package: Path, out: Path, name: str, data: bytes | None) -> None:
    """Copy `package` to `out`, replacing `name` with `data` (or adding it if absent)."""
    with zipfile.ZipFile(package) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.namelist():
            dst.writestr(item, data if item == name and data is not None else src.read(item))
        if name not in src.namelist() and data is not None:
            dst.writestr(name, data)


@pytest.mark.parametrize(
    ("entry", "data", "message"),
    [
        ("tables/goal.jsonl", b'{"id": "forged"}\n', "checksum mismatch for tables/goal.jsonl"),
        ("db/hub.sqlite", b"not a database", "checksum mismatch for db/hub.sqlite"),
        ("files/extra.txt", b"smuggled", "not in the manifest"),
    ],
)
def test_tampered_package_is_rejected(
    client: TestClient,
    data_dir: Path,
    tmp_path: Path,
    entry: str,
    data: bytes,
    message: str,
) -> None:
    seed(client)
    package = tmp_path / "export.zip"
    export_data(data_dir, package)
    tampered = tmp_path / "tampered.zip"
    _rewrite(package, tampered, entry, data)

    target = tmp_path / "restored"
    with pytest.raises(BackupError, match=message):
        import_data(tampered, target)
    assert not (target / DB_FILENAME).exists()


def _repack(package: Path, out: Path, extra: dict[str, bytes], manifest_edit: Any = None) -> None:
    """Copy `package`, add `extra` entries with valid checksums, optionally edit the manifest."""
    with zipfile.ZipFile(package) as src:
        manifest = json.loads(src.read(MANIFEST))
        entries = {n: src.read(n) for n in src.namelist() if n != MANIFEST}
    for name, data in extra.items():
        entries[name] = data
        manifest["sha256"][name] = hashlib.sha256(data).hexdigest()
    if manifest_edit is not None:
        manifest_edit(manifest)
    with zipfile.ZipFile(out, "w") as dst:
        dst.writestr(MANIFEST, json.dumps(manifest))
        for name, data in entries.items():
            dst.writestr(name, data)


@pytest.mark.parametrize(
    "name", ["files/../escape.txt", "files/..\\escape.txt", "files/C:\\escape.txt", "/abs.txt"]
)
def test_entry_paths_that_could_escape_the_target_are_rejected(
    client: TestClient, data_dir: Path, tmp_path: Path, name: str
) -> None:
    seed(client)
    package, crafted = tmp_path / "export.zip", tmp_path / "crafted.zip"
    export_data(data_dir, package)
    _repack(package, crafted, {name: b"payload"})

    # zipfile normalises some names on write (e.g. "\\" -> "/" on Windows), so a crafted
    # entry is caught either by the path check or because it no longer matches the manifest.
    with pytest.raises(BackupError, match=r"unsafe path|not in the manifest"):
        import_data(crafted, tmp_path / "restored")
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("files/notes/a.txt", True),
        ("db/hub.sqlite", True),
        ("files/../x", False),
        ("files/..\\x", False),
        ("files/C:\\x", False),
        ("C:/x", False),
        ("/abs", False),
        ("files//x", False),
        ("./x", False),
        ("", False),
    ],
)
def test_entry_name_rule(name: str, safe: bool) -> None:
    assert _safe_entry_name(name) is safe


def test_failed_import_leaves_no_partial_target(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    seed(client)
    package, crafted = tmp_path / "export.zip", tmp_path / "crafted.zip"
    export_data(data_dir, package)

    def wrong_counts(manifest: dict[str, Any]) -> None:
        manifest["row_counts"]["task"] = 999

    _repack(package, crafted, {}, wrong_counts)
    restore_parent = tmp_path / "parent"
    with pytest.raises(BackupError, match="row counts differ"):
        import_data(crafted, restore_parent / "restored")
    assert list(restore_parent.iterdir()) == []


def test_import_refuses_a_non_empty_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "busy"
    target.mkdir()
    (target / "keep.txt").write_text("user file")

    assert pos(["import", "--in", str(SCHEMA_0001_PACKAGE), "--data-dir", str(target)]) == 1
    assert "is not empty" in capsys.readouterr().err
    assert sorted(p.name for p in target.iterdir()) == ["keep.txt"]


def test_older_schema_package_is_migrated_to_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with zipfile.ZipFile(SCHEMA_0001_PACKAGE) as zf:
        assert Manifest.from_json(zf.read(MANIFEST)).schema_version == "0001"
        assert json.loads(zf.read("tables/alembic_version.jsonl")) == {"version_num": "0001"}
        assert "tables/task.jsonl" not in zf.namelist()

    target = tmp_path / "restored"
    assert pos(["import", "--in", str(SCHEMA_0001_PACKAGE), "--data-dir", str(target)]) == 0
    assert f"schema 0001 -> {head_revision()} (migrated)" in capsys.readouterr().out
    with closing(sqlite3.connect(target / DB_FILENAME)) as conn:
        (version,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == head_revision()

    with hub_client(Settings(data_dir=target)) as client:
        assert client.post("/goals", json={"title": "after upgrade"}).status_code == 201


def test_cli_export_reports_rows(client: TestClient, data_dir: Path, tmp_path: Path) -> None:
    seed(client)
    out = tmp_path / "cli.zip"
    assert pos(["export", "--data-dir", str(data_dir), "--out", str(out)]) == 0
    assert out.is_file()


def test_export_without_a_database_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="no Hub database"):
        export_data(tmp_path / "empty", tmp_path / "x.zip")


def test_forged_database_with_matching_checksum_fails_cleanly(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    seed(client)
    package, crafted = tmp_path / "export.zip", tmp_path / "crafted.zip"
    export_data(data_dir, package)
    _repack(package, crafted, {"db/hub.sqlite": b"this is not a database at all"})

    with pytest.raises(BackupError, match=r"^import failed: "):
        import_data(crafted, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_import_target_that_is_a_file_is_explained(tmp_path: Path) -> None:
    target = tmp_path / "a-file"
    target.write_text("not a directory")
    with pytest.raises(BackupError, match="exists and is not a directory"):
        import_data(SCHEMA_0001_PACKAGE, target)


def test_export_leaves_no_partial_file(client: TestClient, data_dir: Path, tmp_path: Path) -> None:
    seed(client)
    out = tmp_path / "export.zip"
    export_data(data_dir, out)
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("export")) == [
        "export.zip"
    ]


def test_export_while_another_connection_writes_is_consistent(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    seed(client)
    stop = threading.Event()
    written: list[int] = []

    def writer() -> None:
        with closing(sqlite3.connect(data_dir / DB_FILENAME, timeout=10)) as conn:
            i = 0
            while not stop.is_set():
                conn.execute(
                    "INSERT INTO goal (title, notes, status, due_date, id, owner_id,"
                    " created_at, updated_at, source, version)"
                    " VALUES (?, '', 'active', NULL, ?, 'local', '2026-11-10 00:00:00',"
                    " '2026-11-10 00:00:00', 'test', 1)",
                    (f"bulk {i}", f"{i:026d}"),
                )
                conn.commit()
                i += 1
                written.append(i)

    errors: list[BaseException] = []

    def guarded_writer() -> None:
        try:
            writer()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=guarded_writer)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while len(written) < 20 and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(written) >= 20, f"writer did not get going: {errors}"
        written_before_export = len(written)
        manifest = export_data(data_dir, tmp_path / "busy.zip")
        written_after_export = len(written)
    finally:
        stop.set()
        thread.join(timeout=30)
    assert not errors, errors
    assert written_after_export > written_before_export, "no write overlapped the export"

    package = tmp_path / "busy.zip"
    with zipfile.ZipFile(package) as zf:
        jsonl_goals = len(zf.read("tables/goal.jsonl").decode("utf-8").splitlines())
    restored = tmp_path / "restored"
    import_data(package, restored)
    with closing(sqlite3.connect(restored / DB_FILENAME)) as conn:
        (db_goals,) = conn.execute("SELECT COUNT(*) FROM goal").fetchone()
    assert jsonl_goals == db_goals == manifest.row_counts["goal"] >= 21


def test_programming_errors_are_not_disguised_as_bad_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(_package: Path) -> Any:
        raise KeyError("bug in our code")

    monkeypatch.setattr(backup_service, "_read_verified", broken)
    with pytest.raises(KeyError, match="bug in our code"):
        import_data(SCHEMA_0001_PACKAGE, tmp_path / "restored")


def test_rename_is_retried_while_windows_holds_a_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup_service.time, "sleep", lambda _s: None)
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked by indexer")
        return "renamed"

    assert backup_service._retry_on_lock(flaky) == "renamed"  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 3

    def always_locked() -> None:
        raise PermissionError("still locked")

    with pytest.raises(PermissionError):
        backup_service._retry_on_lock(always_locked)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.skipif(sys.platform == "win32", reason="needs a case-sensitive file system")
@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["Notes.txt", "notes.txt"], "differ only in letter case"),
        (["a:b.txt"], "cannot be exported portably"),
        (["a\\b.txt"], "cannot be exported portably"),
    ],
)
def test_export_rejects_file_names_another_os_cannot_restore(
    client: TestClient, data_dir: Path, tmp_path: Path, names: list[str], message: str
) -> None:
    seed(client)
    for name in names:
        (data_dir / "files").mkdir(exist_ok=True)
        (data_dir / "files" / name).write_text("x")
    with pytest.raises(BackupError, match=message):
        export_data(data_dir, tmp_path / "export.zip")
    assert not (tmp_path / "export.zip").exists()
