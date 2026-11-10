# 0009 — Task CRUD API, idempotency and audit log

- Status: accepted (made autonomously while the user was away; review on return)
- Date: 2026-11-10
- Task: T-0002

No new dependencies.

## Decisions taken without the user

1. **Three small edits outside T-0002's `allowed_paths`.**
   - `pyproject.toml`: the new `tasks` and `audit` modules must be listed in the
     import-linter contracts (ADR 0008).
   - `apps/hub/core/settings.py`: adds `POS_OWNER_ID` (default `local`). The card asks
     for "a single local owner from config".
   - This ADR file.
2. **A task cannot be set to `done` yet.** Creating or updating a task to `done` returns
   409. CLAUDE.md says a task needs an Evidence row to be done, and Evidence arrives in
   S6. Goals and projects can be set to `done`.
3. **Execution mode default.** A task with tag `course:CIS` defaults to `human_led`.
   Any other task defaults to `collaborate`. An explicit `execution_mode` is honoured,
   even for CIS tasks. *Open question:* should CIS tasks be forced to `human_led`?
   Forcing it is a one-line change in `_task_rules`.
4. **Idempotency.**
   - Keys are unique per owner and never expire.
   - A replay returns 201, the resource's *current* state, and the header
     `Idempotent-Replayed: true`.
   - Reusing a key for a different entity type returns 422.
   - Reusing a key with a *different* body returns 422 (user decision, 2026-11-10,
     matching the IETF idempotency-key draft). The key row stores a SHA-256 of the
     validated body, so key order and explicitly sent defaults do not count as different.
     The column was added to migration 0002 directly because 0002 had not been merged.
   - The key table lives in the `tasks` module because it is the only user. Move it
     to a shared module when a second module needs it.
5. **Audit.**
   - Every write handled by the service gets one AuditEvent: actor, action, entity,
     result, and the redacted payload or changes.
   - A rejected write (404/409/422 raised by the service) is rolled back, then audited
     with that result. An unexpected error is audited as `error` with only the exception
     type, so database text cannot leak into the log. An idempotent replay is audited as
     `replayed`.
   - A successful create also logs the stored state (e.g. the resolved `execution_mode`).
   - Redaction covers `name=value` / `name: value` (quoted or not, any `*_token`,
     `*_secret`, `*password` name), `Authorization` headers with any scheme, bare
     `Bearer`/`Token`/`Digest` values, `user:pass@` in URLs, and `sk-`, `ghp_`, `AKIA` keys.
     It is pattern based, so an unusual secret shape can still slip through: an unquoted
     multi-word value (`secret: abc def` keeps `def`) or free prose ("my password is
     hunter2"). Key-name matching errs toward safety, so a harmless key such as
     `tokens_used` is also redacted.
   - Replaying a key whose resource was since deleted returns 404 (audited `not_found`).
   - A request that fails schema validation never reaches the service, so it is not
     audited.
   - Known limits are tracked in `docs/backlog.md`.
   - Only the audit copy is redacted. The entity itself stores what the user sent.
6. **Delete.** Deletes are hard, with no version check. A goal, project or task that is
   still referenced (foreign key, or another task's `depends_on`) returns 409.
7. **Hierarchy is optional.** `project.goal_id` and `task.project_id` may be null, so a
   loose task is allowed. A workspace is bound to exactly one project or task.
8. **Dependencies.** `depends_on` is a JSON list of task ids. The service checks that
   each id exists and is not the task itself. It does not detect longer cycles.
9. **Concurrent writes return 409, not 500.** SQLite in WAL mode rejects a write from a
   transaction whose read snapshot is stale (`SQLITE_BUSY_SNAPSHOT`). The service maps
   that, and SQLAlchemy's `StaleDataError`, to 409 "retry". The alternative,
   `BEGIN IMMEDIATE` for every transaction, would serialise reads too, so we did not
   take it.
10. **Migrations use frozen column types.** For example, `sa.DateTime()` instead of the
   app's `UTCDateTime`, so later code changes cannot alter an old migration. The
   physical SQLite type is the same. `apps/hub/migrations/all_models.py` imports every
   module's models, and a test fails if the models and the migrations differ.
11. **Routes are built from one registry (`tasks.service.KINDS`).** Adding an entity is
    one `Kind(...)` entry. Pyright's `reportInvalidTypeForm` is off in `tasks/api.py`
    only, because the body types there are variables.
12. **Contracts.** The request and response models are Python (`packages/contracts/tasks.py`).
    `packages/contracts/openapi.json` is exported by `tools/export_openapi.py`, and a test
    fails when it is stale. Generating TypeScript types from it is left for S4 (PWA).
