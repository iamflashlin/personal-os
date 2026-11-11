# 0005 — The Hub is a modular monolith

- Status: accepted
- Date: 2026-11-10
- Source: HANDOFF §3 items 1, 8, 9; §4.1; §4.4. Recorded by D0-06, after ADRs 0008 and 0009
  had already built on this decision.

## Context

The source design lists 19 logical modules, an event bus, a workflow engine, a sync
service, a vector store, PostgreSQL, Tauri and Docker. One person builds this with AI
agents on one Windows laptop. Most of those modules have no use in V0.1. Separate
services would bring separate deployments, network calls and failure modes before any
feature works. We still want seams, so that a module can be split out later and agents
cannot quietly couple modules.

## Decision

- The Hub (`apps/hub`) is one FastAPI process and one Python package.
- Each module is a subpackage with a public `service.py`. Modules talk to each other
  only through those functions and Pydantic types. ORM rows (`models.py`) stay private.
- `apps/hub/core` holds shared infrastructure (settings, engine, `Entity` mixin). It
  imports no module.
- Two import-linter contracts in `pyproject.toml` enforce this in the gate: layers
  (entry points > modules > core) and independence (cross-module imports only via
  `service`). A test fails if a module is missing from either contract (ADR 0008).
- When needed, the event log and the job queue are SQLite tables in the Hub, not a broker.
- Not in V0.1: event bus, workflow engine, sync service, vector store, PostgreSQL,
  Tauri, agent framework. Docker is used only when the Hub moves to a server; local
  development uses uv lockfiles.
- The desktop agent and the PWA are separate processes, because they run on the
  user's desktop and phone (ADR 0007).

## Alternatives considered

- Microservices, one per module: real network boundaries, but deployment, tracing and
  versioning cost with no user benefit at this size.
- One package with no internal boundaries: fastest start, but agents would couple
  modules, and splitting later would need a rewrite.
- Boundaries by convention only: the reviewer would catch some violations, not all.
- A custom AST checker instead of import-linter: more code to maintain (ADR 0008).

## Consequences

- One process to run (`uv run python -m apps.hub`) and one database. An audit row
  commits in the same transaction as the change it describes.
- Adding a module means `__init__.py`, `service.py`, and an entry in both contracts.
- Splitting a module into its own process later is possible but not free: service
  functions take a SQLAlchemy `Session`, and audit rows join the caller's transaction
  (invariant D6). A split module needs new signatures and an outbox table or similar
  instead of same-transaction audit.
- import-linter checks imports, not types. "service.py returns Pydantic types, not ORM
  rows" is checked by the reviewer (ADR 0008, known gap).
- If one module crashes the process, the whole Hub stops. This is acceptable for one user.
