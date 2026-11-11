# 0010 — Export / import package format v1

- Status: accepted (made autonomously; user asked for decisions to be recorded)
- Date: 2026-11-10
- Task: T-0003. No new dependencies.

## Decisions

1. **One zip per export.** Layout: `manifest.json`, `db/hub.sqlite`,
   `tables/<table>.jsonl`, `files/...`. The manifest holds `format_version` (1),
   `schema_version` (the Alembic revision), `row_counts` per table, and a SHA-256 for
   every other entry.
2. **Import restores from the SQLite backup, not from the JSONL.** The backup is exact:
   types, indexes, constraints, the Alembic version. The JSONL files are a readable,
   tool-independent copy of every row (sorted by primary key, BLOBs as
   `{"$base64": ...}`), checked by checksum. Replaying JSONL would need a second code
   path per table that could drift from the schema.
3. **Export works while the Hub runs.** It uses SQLite's online backup API to snapshot
   the database. It never copies the WAL files by hand (ADR 0006).
4. **Import is strict.**
   - The target must be absent or empty.
   - Every manifest entry must be present, and its checksum must match.
   - No unlisted entry may be present (a smuggled file counts as tampering).
   - No absolute or `..` paths.
   - The row counts after restore must equal the manifest.
   - Only then does it migrate to the current head.
   - Any failure prints one plain message and exits 1.
   - Everything is written to a staging directory next to the target and renamed into
     place only after all checks and the migration succeed. A failed import leaves no
     partial target behind.
   - Entry names must be plain relative `/` paths, with no backslash, drive, root, `.`
     or `..`. Every written file must resolve inside the staging directory.
   - **Threat model:** checksums detect corruption and accidental edits. They do not stop
     deliberate forgery, because `manifest.json` itself is not signed. Someone who edits
     a file and its checksum together passes. Signing or encrypting packages is out of
     scope (S7).
5. **Export is atomic and checks names early.** The zip is written as `<out>.part` and
   renamed with `os.replace`, so a crash never leaves a truncated package. File names that
   another OS could not restore (`\`, `:`, `..`, or two names that differ only in case)
   are rejected at export time, not discovered on the new machine.
   Import also runs `PRAGMA integrity_check` before counting rows. The CLI prints
   `schema 0001 -> 0002 (migrated)` when it upgraded the package. Any low-level failure
   (disk, SQLite, bad encoding, migration) becomes one `pos ...: ... failed: <reason>`
   line with exit 1. A bug in this code is not hidden: unexpected exceptions keep their
   traceback. Renames retry briefly when Windows (antivirus, indexer) holds a fresh file.
6. **The snapshot is written next to the output zip, not in `%TEMP%`.** It can be as large
   as the database, and drive C is nearly full (CLAUDE.md).
7. **The fixture for "older schema" is a committed zip** (`tests/hub/fixtures/
   export-schema-0001.zip`, a database at revision 0001), rebuilt by
   `uv run python -m tests.hub.fixtures.build_fixtures`. Because it is a real old
   package, a future change that breaks reading older exports fails the test.
8. **No encryption, no offsite copy** (card out of scope; restic is S7). A package contains
   everything, including task notes as the user typed them. Treat it like the data
   directory itself.

## Known limits (v0)

- Export and import hold the whole database and file tree in memory. Before `files/`
  holds large data, stream entries (`zf.write(path)`, chunked hashing via `zf.open`).
- `files/` is read after the database snapshot, so the two are not captured in the same
  instant. This is harmless while the Hub writes no files.
- The 0001 fixture has no user rows, because 0001 is an empty baseline. When migration
  0003 lands, add a seeded 0002 fixture and assert its rows survive the upgrade.
- On Linux the restored data directory has mode 0700 (it starts as a `mkdtemp` staging
  directory). That is acceptable for private data.
- Add `*.zip binary` to `.gitattributes`. Today git's own binary detection keeps the
  fixture intact.

## Found while building

Python's `with sqlite3.connect(...)` commits but does **not** close the connection. On
Windows the open handle locked the file, and deleting the temporary snapshot failed. All
backup code now uses `contextlib.closing`. Recorded in `docs/lessons.md` candidates in
the PR, since that file is outside this card's allowed paths.
