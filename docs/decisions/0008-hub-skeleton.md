# 0008 — Hub skeleton: dependencies, layout and defaults

- Status: accepted (made autonomously while the user was away; review on return)
- Date: 2026-11-10
- Task: T-0001

## Dependencies

| Dependency | Where | Why | Alternative rejected |
|---|---|---|---|
| fastapi 0.162 | runtime | HTTP API (HANDOFF §4.8) | — |
| uvicorn 0.54 | runtime | ASGI server for `python -m apps.hub` | hypercorn: no advantage here |
| sqlalchemy 2.1 | runtime | ORM, optimistic locking via `version_id_col` (HANDOFF §4.8) | raw sqlite3: we would re-implement locking and types |
| alembic 1.20 | runtime | schema migrations, applied on Hub startup (HANDOFF §4.8) | — |
| pydantic-settings 2.16 | runtime | typed `POS_*` config | hand-written `os.environ` parsing |
| python-ulid 4.1 | runtime | ULID primary keys (HANDOFF §4.3) | `ulid-py`: unmaintained |
| import-linter 2.16 | uv `dev` | module-boundary contracts in the gate (HANDOFF §4.1) | a custom AST script |
| httpx 0.28 | uv `dev` | FastAPI `TestClient` and `scripts/verify/hub.py` | — |

Known: Starlette now warns that `TestClient` should use `httpx2` instead of `httpx`.
The card names `httpx`, and it works, so we keep it. Revisit when Starlette drops it.

## Decisions taken without the user

1. **Started T-0001 although D0-06 (ARCHITECTURE.md) is still `todo`.** The user asked
   for T-0001 directly, and nothing in T-0001 needs that document. Risk: D0-06 may later
   want a different layout. This ADR records the layout so D0-06 can adopt or revise it.
2. **Config comes from environment variables only. The Hub does not load a `.env` file.**
   This avoids the Hub (and agents running verification) quietly reading local secrets.
   If you want `.env` loading, add `env_file=".env"` to `Settings.model_config`.
3. **Defaults.** `POS_DATA_DIR` = `<repo>/data` (already gitignored, on drive D:),
   `POS_HUB_HOST` = `127.0.0.1`, `POS_HUB_PORT` = `8765`. The database file is
   `<data_dir>/hub.sqlite`.
4. **Layout.** `apps/hub/core` holds shared infrastructure (settings, engine, the
   `Entity` common-columns mixin, the UTC type). Every other subpackage of `apps/hub` is
   a module (`system` for now; `tasks`, `audit` arrive in T-0002). The `/health` logic
   lives in the `system` module so the boundary contract has a real module to guard.
5. **Two import-linter contracts** in `pyproject.toml`. A layers contract
   (entry points > modules > core) keeps `core` from importing modules. An independence
   contract lets a module reach another only through `<module>.service`. A test fails if
   a new subpackage of `apps/hub` is missing from either contract.
   `apps/hub/migrations/__init__.py` exists so import-linter can see the package.
6. **Python contracts** live directly in `packages/contracts/*.py` and import as
   `packages.contracts.<name>` (namespace package `packages`, no install step), next to
   the existing TypeScript in `packages/contracts/ts/`.
7. **Timestamps.** `UTCDateTime` stores UTC and rejects naive datetimes at write time,
   because SQLite silently drops timezone information.
8. **Optimistic locking.** `version` starts at 1 and SQLAlchemy increments it. A stale
   write raises `StaleDataError`. T-0002 maps that to HTTP 409.
9. **Migrations run on startup** in the FastAPI lifespan, in one transaction. A Hub that
   cannot migrate does not start. Python's sqlite3 driver normally autocommits DDL, so
   `make_engine` puts the driver in autocommit mode and emits `BEGIN` itself
   (SQLAlchemy's pysqlite recipe). A test proves a failed transaction leaves no table.
10. **Connection PRAGMAs:** `journal_mode=WAL`, `foreign_keys=ON` (SQLite ignores foreign
    keys otherwise), `busy_timeout=5000` ms (wait for a lock instead of failing at once).

## Known gaps

- The ignore rule `apps.hub.** -> apps.hub.*.service` allows any import of another
  module's `service`. If a `service.py` re-exports its ORM rows, the "Pydantic types
  only" half of the boundary rule is not enforced. Reviewers check that by hand.
- On Windows the verify script stops the Hub with `terminate()`, which kills it outright.
  The graceful shutdown path (`engine.dispose()`) is not exercised by verification.

## Consequences

- Run the Hub with `uv run python -m apps.hub`.
- New Hub module: create `apps/hub/<name>/__init__.py` and `service.py`, then add the
  module to both contracts (the test tells you if you forget).
- A module with tables must import its models in `apps/hub/migrations/env.py`, or
  Alembic autogenerate will not see them.
