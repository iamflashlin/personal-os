# 0018 — Credential store: secrets in Windows Credential Manager, metadata in SQLite

- Status: accepted (decided by Claude; HANDOFF §4.6 chose keyring and §4.7 chose
  "re-enter credentials on a new PC", so no security-model choice is new here)
- Date: 2026-11-10
- Card: T-0011. Needed by the email and Canvas integrations (T-0012 and later).

## Decisions

1. **Where secrets live.**
   - The value goes to Windows Credential Manager through `keyring`. The service name is
     `POS_CREDENTIALS_SERVICE` (default `personal-os-hub`) and the entry name is
     `<owner>:<credential name>`.
   - SQLite holds only the `credential` row: name, note and the times it was set and last
     used. It holds no length, hash or prefix of the secret.
   - Exports therefore carry no secret, and on a new PC the user enters credentials again
     (HANDOFF §4.7).
2. **No way to read a secret over HTTP.**
   - The routes are `PUT /credentials/{name}` (set or replace), `GET /credentials`
     (metadata) and `DELETE /credentials/{name}`. A test checks the OpenAPI document for
     exactly these.
   - Hub code reads a secret with `credentials.service.reveal`, which audits every use and
     updates `last_used_at`.
   - The request body uses `SecretStr`, so the value never shows in a repr or a log.
   - A refused request never echoes what was sent. The Hub's validation-error handler
     drops FastAPI's `input` and `ctx` fields for every route, so a mistyped, oversized
     or misplaced secret is not sent back to the caller, who might log or show it.
3. **Order of writes.**
   - Put: the store is written first, then the row. If the database write fails, the
     new value is already in the store and nothing points at a missing secret.
   - Delete: the store entry goes first, then the row. If the row survives, `reveal`
     says "not set; enter it again".
   - A row whose secret vanished, for example because the user cleaned up Credential
     Manager, reads as not found.
   - If creating a new credential fails after its secret reached the store, the secret
     is removed again, so nothing hidden is left that the Hub could not list or delete.
     A replace that fails after the store write leaves the new value live (the error
     still reaches the caller).
   - Writes for credentials hold a process-wide lock (one Hub process, ADR 0014), so two
     requests for the same name cannot interleave their store and row writes.
4. **Local-only gap.** Until S8, any local process could set or delete a credential, as
   ADR 0014 D4 accepted for the other endpoints. None can read one back.
5. **Size limit.** Windows Credential Manager holds at most 2560 bytes per secret, and
   keyring stores text as UTF-16, so the limit is 1280 ordinary characters. A probe on
   this PC stored 1280 and refused 1281. Longer secrets are refused with 422, and any
   other refusal by the store becomes a 422 that names only the error type. **未验证:**
   OAuth access tokens (often 1.5–2.5k characters) will need another approach, such as
   splitting across entries or keeping only the refresh token. Spike (≤ half a day) in
   the first OAuth connector card.
6. **`keyring` becomes a runtime dependency of the Hub.** It moves from the `desktop`
   group to `[project] dependencies`, still at the version the user approved in ADR 0014
   D1.
7. **Tests never touch this PC's Credential Manager.** `tests/hub/support.hub_client` uses
   a `MemorySecretStore` unless a test passes another one, and `tests/conftest.py` swaps
   keyring's backend for one that always fails, for the whole session. Only
   `scripts/verify/hub.py credentials` uses the real store, under a throwaway service
   name that it deletes afterwards.

## Consequences

- An integration handler gets its token with `reveal(..., "canvas.token")`. If the user
  has not entered it, the handler fails with "not set", and the job becomes `dead` after
  its retries, visible at `GET /jobs?status=dead`.
- A later card adds a web page for entering credentials, together with the integrations UI.
