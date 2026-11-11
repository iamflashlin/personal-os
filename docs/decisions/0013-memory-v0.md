# 0013 — Second brain v0: memory model and Chinese-capable search

- Status: accepted (made autonomously within HANDOFF §4.3; the user asked for decisions
  to be recorded)
- Date: 2026-11-10
- Task: T-0005 (VISION direction 1). No new dependencies.

## Context

VISION direction 1: remember the user's goals, preferences, facts and past decisions, so
they never re-explain context. HANDOFF §4.3 already fixes the fields: kind, body,
provenance (raw / user_confirmed / ai_inferred / verified), confidence, expires_at,
sensitivity. Search must work in Chinese and English (ADR 0006: SQLite FTS5).

## Spike: FTS5 and Chinese (resolves the 未验证 in ADR 0006 for Windows)

On this machine (Python 3.12, SQLite 3.53.1), `ENABLE_FTS5` is compiled in. Findings:

- The default `unicode61` tokenizer treats a run of CJK characters as one token. Searching
  `学习` finds nothing in `我喜欢早上学习`; only the whole run matches.
- The `trigram` tokenizer finds any substring of **3 or more** characters, in any language,
  ranked by bm25. It cannot match a 1–2 character term with `MATCH`.

ubuntu-latest is covered by the same tests in CI.

## Decisions

1. **One `memory` table** with the HANDOFF fields plus `source_ref` (free text: a URL, a
   file, a chat). Kinds: preference / fact / decision / experience. Sensitivity:
   `normal` / `private` / `secret`.
2. **Search = FTS5 `trigram` for terms of 3+ characters, plus a substring scan for shorter
   terms.**
   - Terms are split on whitespace and ANDed.
   - Each term is quoted as a phrase, so `OR`, `NOT`, `"` and `*` are treated as text.
   - LIKE wildcards are escaped.
   - The FTS index stores `memory_id` (unindexed) with a copy of the body, and is joined
     on `memory.id`, never on rowid. An external-content index keyed by rowid was tried
     first and rejected: VACUUM may renumber rowids of a table without an INTEGER PRIMARY
     KEY, and an Alembic batch migration (`render_as_batch=True`) rebuilds a table by
     copying it. A test moves every rowid and checks that search still works. The cost is
     a second copy of each body in the same database file.
   - Three triggers (insert, delete, update of id or body) keep the index in the same
     transaction as the change, so code cannot forget it.
   - The substring scan is linear, and so are the trigger deletes
     (`DELETE FROM memory_fts WHERE memory_id = ...` on an unindexed column); both are fine
     at one person's scale.
   - **Any migration that rebuilds `memory` (Alembic batch mode) drops these triggers with
     the old table.** It must recreate them and rebuild `memory_fts`.
     `test_fts_triggers_exist_at_head` fails if they are missing at head.
   - Migration 0004 was edited in place before merge (rowid → id keying). A data
     directory migrated with the first draft of 0004 (only possible on the unmerged branch,
     e.g. `data/verify/*`) must be recreated. The tests and the
     verify script prove that 2-character Chinese words such as `学习` and `英语` are
     found.
3. **Provenance is honest.**
   - `verified` cannot be set through the API. It is reserved for memories backed by
     Evidence (S6), mirroring "a task is never done from model output alone".
   - `POST /memories/{id}/confirm` is the user's "this is right": it sets
     `user_confirmed` and confidence 1.0.
   - A correction is a PATCH with the version last read. The audit log keeps the history
     of changes.
4. **Sensitive memories stay out of the audit log.** For `private` and `secret` memories,
   and for any change to or from those levels, the audit copy stores the body's length
   and SHA-256 only. `secret` memories are also left out of search unless
   `include_secret=true` is passed.
5. **Expiry.** `expires_at` must be timezone-aware (422 otherwise). Expired memories are
   left out of the list and of search unless `include_expired=true`; they are not deleted.
6. **The audited-write helper, actor and domain errors are shared.** They moved from
   `tasks.service` to `audit.service.audited`, `core/domain.py` and `core/http.py` in a
   behaviour-preserving commit, so every module records one audit event per write the
   same way.
7. **Migrations and drift.** Migration 0004 creates the table, then the FTS table and
   triggers with raw SQL. `migrations/all_models.include_object` keeps `memory_fts*` out
   of autogenerate and out of the model/migration drift test. Export/import already copies
   the SQLite file, so the index survives a move to a new machine (tested).

## Not in this card

- Vector search (P1).
- Memories extracted automatically by a model (S5): when that comes, it must create them
  as `ai_inferred` with a confidence below 1.
- Links between memories and tasks.
- A web UI for memories.
