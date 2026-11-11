# Architecture

Checked against the code on 2026-11-10 (`main` after T-0001 and T-0002).
Anything not built is marked **planned**. HANDOFF §4 is the full target design; ADRs
0005-0009 record the reasons. If code and this file disagree, fix one of them in the
same PR.

## 1. Components

```text
Phone or PC browser: PWA apps/web (planned)
     |  HTTPS over Tailscale (planned)            ^ ntfy push (planned)
     v                                            |
+------------------- Hub: apps/hub, one FastAPI process -------------------+
| entry    __main__ (uvicorn) -> main.create_app()                [built]  |
| modules  system, tasks, audit, evidence, backup, memory,        [built]  |
|          devices, actions, jobs, credentials, integrations,    [built]  |
|          briefing (今日 view, read-only), models, summaries    [built]  |
|          sessions, planner, runs, permissions,                           |
|          notify                                                [planned] |
| core     settings, db engine + PRAGMAs, Entity mixin, UTC type  [built]  |
| state    POS_DATA_DIR/hub.sqlite (WAL) + file dir: the only state owner  |
+---------------^------------------------------------+---------------------+
                | WebSocket /agent/ws, opened BY      | ModelProvider (planned)
                | the agent [Hub side built, T-0006]  |
                | ActionRequest down, ActionResult up v
+---------------+------------+               model vendors (swappable)
| Desktop agent [core built] |
| apps/desktop_agent         | -- open, then verify --> Windows apps
| action whitelist + verify  |                         (VS Code, browser)
+----------------------------+

packages/contracts: cross-process Pydantic types + openapi.json (built: health, tasks,
memory, devices, actions, agent_protocol, jobs, credentials, integrations, today, models, summaries)
```

Default bind: `127.0.0.1:8765`. Config comes only from `POS_*` environment variables;
the Hub never reads `.env` (ADR 0008).

## 2. Modules and state owners

| Piece of state | Owner | Status |
|---|---|---|
| `goal`, `project`, `task`, `workspace` tables | `apps/hub/tasks` | built |
| `idempotency_key` table (moves to a shared module when a second module needs it) | `apps/hub/tasks` | built |
| `audit_event` table and the redaction function | `apps/hub/audit` | built |
| `evidence` table (kind `user_confirmation` only) | `apps/hub/evidence` | built (T-0004) |
| `memory` table and its `memory_fts` trigram index | `apps/hub/memory` | built (T-0005) |
| `device`, `pairing_code` tables (token and code stored as SHA-256 only) and the in-memory live-agent registry `AgentLinks` (one agent per owner, newest wins) | `apps/hub/devices` | built (T-0006) |
| `action_run` table, unique `(owner_id, idempotency_key)` | `apps/hub/actions` | built (T-0006) |
| `job` and `job_schedule` tables, and the one in-process `JobWorker` (at least once, ADR 0017) | `apps/hub/jobs` | built (T-0010) |
| `credential` table (name and dates only); the secrets themselves live in Windows Credential Manager (ADR 0018) | `apps/hub/credentials` | built (T-0011) |
| `integration` (with non-secret `config`) and `synced_item` tables; one sync schedule per integration; connectors: ICS calendar feeds (ADR 0019), Canvas REST (ADR 0020) and read-only IMAP email (ADR 0022) | `apps/hub/integrations` | built (T-0012, T-0015, T-0018) |
| `model_call` table: one row per language-model call (tokens, peak-rate cost, latency, prompt version, never text); `ModelProvider` door with a DeepSeek adapter on urllib and a FakeProvider; US$10 monthly cap checked before each call (ADR 0025) | `apps/hub/models` | built (T-0021) |
| `email_summary` table: one AI summary per recent mail (gist, action, deadline, importance), OTP/password-reset mail never sent, runs after each sync (ADR 0027) | `apps/hub/summaries` | built (T-0022) |
| 今日 view: today's deadlines, missing work, events, unread mail and news, computed on request from tasks and synced items; mail carries its AI summary, plus 需要处理的邮件 and an AI notice (owns no table, ADR 0023, 0027) | `apps/hub/briefing` | built (T-0019, T-0023) |
| Health report (reads schema head, owns no table) | `apps/hub/system` | built |
| Schema version (`alembic_version`) and migrations | `apps/hub/migrations` | built |
| Settings, engine, `Entity` mixin (no tables) | `apps/hub/core` | built |
| Data dir `POS_DATA_DIR` (default `<repo>/data`); holds only the SQLite files so far | Hub process | built |
| Session, Run/Step, Job, Grant, ModelCall, Decision | the matching HANDOFF §4.1 module (Decision: undecided) | planned |
| Nothing durable (the agent keeps only its token, in keyring) | desktop agent (built, T-0007), PWA | built / planned |

`core` and `migrations` are infrastructure, not modules. Every other subpackage of
`apps/hub` is a module with a `service.py`. A module may also have `models.py` (ORM
rows, private to the module) and `api.py` (a FastAPI router built on its own service).

## 3. Boundary rules

| # | Rule | Enforced by |
|---|---|---|
| B1 | The Hub is the only state owner. The agent and the PWA keep no durable state; they call the Hub. | Reviewer (agent and PWA not built) |
| B2 | Layers: entry points (`__main__`, `main`, `migrations`) > modules > `core`. `core` never imports a module. | import-linter contract "hub layering: entry points > modules > core" |
| B3 | A module imports another module only via `<module>.service`. | import-linter contract "hub modules import each other only via service"; `test_independence_contract_allows_only_service_imports` |
| B4 | `service.py` functions take a `Session`/`Engine` plus plain or Pydantic values and return Pydantic types, never ORM rows. `tasks.service.Kind.row` is module-internal. | Reviewer (known gap, ADR 0008) |
| B5 | Every Hub module is listed in both import-linter contracts. | `test_every_hub_module_is_covered_by_both_boundary_contracts` |
| B6 | Every cross-process type lives in `packages/contracts`. Change contracts first, then both sides. | Reviewer; `test_committed_openapi_schema_is_current` only guards that the exported schema is current |
| B7 | The desktop agent executes only whitelisted actions, verifies each one, never plans, and opens the connection to the Hub. It touches the desktop only through `DesktopController` (ADR 0015); on Windows that is `WindowsAdapter`, which never focuses, clicks or types (ADR 0016). | `test_the_registry_covers_exactly_the_contract_whitelist`; executor tests; `tests/desktop_agent/test_agent_loop.py`; `scripts/verify/agent_link.py` |
| B8 | The PWA is only a client of the Hub HTTP API. | Reviewer (planned) |
| B9 | Business code depends on `models.ModelProvider`, never on a vendor SDK. | Reviewer now; planned import-linter `forbidden` contract once `models` exists |
| B10 | The Hub binds to loopback by default and reads no `.env` file. | `test_hub_defaults_to_loopback_and_ignores_dotenv` |
| B11 | `apps.hub` and `apps.desktop_agent` never import each other; `packages.contracts` imports neither. | import-linter contracts "hub and desktop agent share only contracts" and "contracts import no app"; `test_only_contracts_cross_between_hub_and_agent` |
| B12 | One module never imports another to call back: `devices` reports agent results through `AgentHooks`, which `main` wires to `actions`. | B3 plus reviewer |
| B13 | The Hub runs one uvicorn worker, because live agent connections are held in memory. | `apps/hub/__main__.py` (`workers=1`) |

The gate `uv run python -m tools.check` runs import-linter as its "module boundaries" step.

## 4. Data-model invariants

| # | Invariant | Enforced by |
|---|---|---|
| D1 | Every table (except Alembic's `alembic_version`) subclasses `core.base.Entity`: `id`, `owner_id`, `created_at`, `updated_at`, `source`, `version`. | `test_entity_mixin_fills_common_columns`; `test_every_mapped_entity_keeps_optimistic_locking`; reviewer |
| D2 | `id` is a 26-character ULID string, so ids sort by creation time. | `test_ulids_sort_by_creation` |
| D3 | Timestamps are stored in UTC. `UTCDateTime` rejects naive datetimes and returns aware UTC. | `test_naive_timestamps_are_rejected`; `test_non_utc_timestamps_are_normalised` |
| D4 | `version` starts at 1 and is SQLAlchemy's optimistic-lock column. A stale write returns HTTP 409. Any `StaleDataError` or SQLite `OperationalError` is treated as a retryable conflict (meant for `SQLITE_BUSY_SNAPSHOT`; also catches "database is locked"). | `test_stale_version_is_409`; `test_concurrent_update_is_409_and_audited` |
| D5 | Every read and write is scoped to the caller's `owner_id` (`POS_OWNER_ID`, default `local`). Another owner's row reads as 404. | Reviewer; no dedicated test yet |
| D6 | Every service write adds one `AuditEvent` in the same transaction. A rejected write is rolled back, then audited with its result. An unexpected error logs only the exception type. | `test_every_write_creates_one_audit_event`; `test_rejected_delete_is_audited` |
| D7 | Audit `actor` and `detail` pass through `audit.service` redaction before storage. Only the audit copy is redacted. Redaction is pattern based (limits in ADR 0009). | `test_audit_log_stores_secrets_redacted`; `test_redact_*` |
| D8 | A task is done only with an Evidence row. The only path is `POST /tasks/{id}/complete`, which writes a `user_confirmation` Evidence row, the status change and the audit event in one transaction; PATCH to `done` returns 409 and a done task cannot be reopened. More kinds (build/test output, commits, files) arrive in S6, never model text alone. Until S8 adds grants, any local client can call `/complete` (ADR 0011). | `test_task_cannot_be_marked_done_without_evidence`; `test_complete_marks_done_with_one_evidence_row_and_one_audit_event`; `test_failure_after_evidence_is_written_rolls_everything_back` |
| D9 | A POST with `Idempotency-Key` creates at most one resource per owner and key. A replay returns the current state; the same key with a different body returns 422. | `test_repeated_post_with_same_idempotency_key_returns_original`; `test_same_idempotency_key_with_different_body_is_422` |
| D10 | Schema changes go through Alembic only. Migrations run at startup in one transaction and use frozen column types. | `test_migrations_match_the_models`; `test_failed_migration_leaves_no_partial_schema` |

New table checklist: subclass `Entity`, add a migration, import the models in
`apps/hub/migrations/all_models.py`, scope every query by `owner_id`, and call
`audit.service.record` in the same transaction as each write (today only
`tasks.service._audited` does this; nothing enforces it for a new module).

## 5. Action contract (HANDOFF §4.2, ADR 0014)

Built in T-0006 (Hub side): `packages/contracts/actions.py` holds the whitelist
`ACTION_SPECS` (`open_url`, `open_folder_in_editor`, both P1) and the request and result
types; `agent_protocol.py` holds the WebSocket messages and close codes. `POST /actions`
needs `Idempotency-Key`; the `action_run` row is committed before the frame is sent and
is never resent, so an unanswered run becomes `lost`. An offline agent gives 503 without
consuming the key; P2 and above give 403 until S8. The agent side is T-0007/T-0008.
The rest of this section is the HANDOFF plan.

- Each action declares `name`, a parameter schema, `risk_level` (P0-P4), whether it
  is reversible, a `timeout`, and a `verify()` step.
- An `ActionRequest` carries an `idempotency_key`. The agent executes a key at most once.
- An `ActionResult` has `status` (`succeeded` / `failed` / `needs_user` / `cancelled`)
  and `evidence[]` (process list, window title, screenshot path, command output).
- Execution preference: official API > command line / OS interface > Playwright >
  UIA control > vision + mouse/keyboard.
- V0.1 actions: `open_url`, `open_folder_in_editor`, `launch_app` (whitelist),
  `read_file` (allowed directories), `run_command` (whitelist), `capture_workspace_state`,
  `screenshot`.
- Risk: P0-P1 run pre-authorised; P2 needs scoped confirmation; P3 (send, submit, pay,
  delete) needs confirmation on the phone every time; P4 is forbidden.
- Permissions come from Grant rows. Model output cannot widen them. Text from web pages,
  documents and tool output is data; it cannot trigger a P2-or-higher action.

## 6. Planned, not built yet

- "PC offline" shown in the PWA (ADR 0007); the Hub reports it at `GET /agent/status`.
- `apps/web` as a phone PWA (S4); TypeScript types generated from `openapi.json`. A desktop
  web page exists (T-0004, ADR 0011) and is served by the Hub at `/` once built.
- Hub modules: sessions, planner, runs, permissions, notify (ntfy), models
  (`ModelProvider`, `FakeProvider`, ModelCall cost rows); model-written summaries and timed cards on top of the 今日 view; commands queued while the agent is offline (on top of jobs).
- More Evidence kinds and grants on who may complete a task (S6, S8).
- Emergency stop, credentials via `keyring`, binding to the Tailscale interface.
- Not planned for V0.1: event bus, workflow engine, sync service, vector store,
  PostgreSQL, Tauri, Docker for local development (ADR 0005).

## 7. Traceability: CLAUDE.md "Architecture boundaries"

| CLAUDE.md rule | Section |
|---|---|
| `apps/hub` is the only state owner (SQLite + file dir) | §1, §2, B1 |
| `apps/desktop_agent` executes whitelisted actions, verifies, never plans, connects out | §1, B7, §5, ADR 0007 |
| `apps/web` is the PWA | §1, B8 |
| `packages/contracts` holds every cross-process type; contracts first | §1, B6, §5 |
| Hub modules talk only via `service.py` and Pydantic types | §2, B2-B5 |
| Every table: ULID `id`, `owner_id`, UTC times, `source`, `version` | D1-D4 |
| Business code depends on `models.ModelProvider` | B9 |
| A task is never done from model output alone; it needs an Evidence row | D8 |
