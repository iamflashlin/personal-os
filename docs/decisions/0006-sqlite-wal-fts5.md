# 0006 — SQLite in WAL mode, FTS5 for text search

- Status: accepted. WAL is in use. FTS5 is planned and not used yet.
- Date: 2026-11-10
- Source: HANDOFF §3 item 8; §4.3; §4.8. Recorded by D0-06, after ADRs 0008 and 0009.

## Context

The Hub is the only state owner (ADR 0005). It runs on one laptop for one user. Later
it must move to a small server and support export and import (HANDOFF §4.7). It needs
transactions and schema migrations now, and full-text search over memory later. It
must not need a separate database server or admin work.

## Decision

- One SQLite file per data directory: `<POS_DATA_DIR>/hub.sqlite`. Files that do not
  belong in rows go in the same data directory.
- Access goes through SQLAlchemy 2. The schema changes through Alembic migrations that
  run at startup (ADR 0008).
- Each connection sets `journal_mode=WAL`, `foreign_keys=ON` and `busy_timeout=5000`.
  WAL lets readers continue while one writer commits.
- Optimistic locking uses the `version` column. A stale write, or SQLite's
  `SQLITE_BUSY_SNAPSHOT`, becomes HTTP 409 (ADR 0009). We do not use `BEGIN IMMEDIATE`.
- Text search will use SQLite FTS5 virtual tables. **FTS5 is not used yet.** No table,
  migration or query uses it. It arrives with the memory module.
- A vector index (P1) will be a separate table that can be rebuilt from the raw rows.
- The event log and the job queue, when built, are ordinary SQLite tables.

## Alternatives considered

- PostgreSQL: better concurrency and multi-user support, but it needs a server process,
  installation and its own backups. Deferred until multi-user or cloud (HANDOFF §4.8).
  SQLAlchemy keeps the switch possible; the SQLite-specific parts (PRAGMAs,
  `BUSY_SNAPSHOT` mapping, FTS5) would need rewriting.
- SQLite in the default rollback-journal mode: a writer blocks readers.
- A separate search engine or vector database: another process to run and keep in sync.
- JSON files: no transactions and no constraints.

## Consequences

- Backup, export and moving to a new machine start from one data directory. `pos export`
  uses SQLite's online backup API plus per-table JSONL and a manifest (HANDOFF §4.7).
- Only one writer at a time. Concurrent writes can return 409 and the client retries.
  This is fine for one user.
- WAL creates `hub.sqlite-wal` and `hub.sqlite-shm` next to the database. Do not copy
  the files by hand while the Hub runs; use the backup API.
- WAL does not work on network file systems. The data directory must be on a local disk.
- SQLite drops timezone information, so `UTCDateTime` stores UTC and rejects naive
  values (ADR 0008).
- Unverified (未验证): that the Python 3.12 `sqlite3` build on Windows and on CI
  ubuntu-latest includes FTS5. Spike (half a day at most): run
  `SELECT sqlite_compileoption_used('ENABLE_FTS5')` and create a throwaway `fts5`
  table on both platforms, as a test in the memory module's first task card.
