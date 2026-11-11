# 0019 — Integrations: accounts, sync as jobs, idempotent items, ICS first

- Status: accepted (decided by Claude; HANDOFF §4.3 lists Integration and CalendarEvent as
  later entities and §5 names the Canvas calendar feed as the fallback; no account is
  connected and no third-party service is authorised here)
- Date: 2026-11-10
- Card: T-0012. Builds on ADR 0017 (jobs) and ADR 0018 (credentials).

## Decisions

1. **`integration` table.** It holds the kind, a display name, the name of the credential
   it uses, `interval_s` (300–86400 s, default 900), the status
   (`never_synced` / `ok` / `error`), the last sync and last success times, `last_error`
   (redacted) and a connector-specific `cursor`. The secret is never stored here.
2. **`synced_item` table.**
   - One row per (integration, item type, external id). It holds a title, body, location,
     URL, start and end, an all-day flag and free `data`.
   - A content hash decides whether a re-sync rewrites the row. Unchanged items keep
     their version and timestamps, so "changed since" is meaningful.
   - Deleting an integration deletes its items through `ON DELETE CASCADE`. Its
     credential stays, because the user may reuse it.
   - Items missing from a later fetch are kept. Whether to drop them is a per-source
     question for the email and Canvas cards.
3. **Sync is a job (at least once).**
   - Each integration gets its own schedule (`integrations.sync:<id>` at its interval),
     created with it and deleted with it. With no integrations nothing runs.
   - The two writes are separate transactions, so both sides repair themselves. At
     startup every integration is given its schedule again, which writes nothing if it
     already matches. A schedule whose integration is gone deletes itself the next time it
     fires.
   - `JobKinds.register_family` routes `name:<id>` kinds to the `name` handler, for
     registered families only. Any other kind containing a colon has no handler.
   - `POST /integrations/{id}/sync` queues one sync now.
   - A failure sets the status to `error` with a redacted message, and the error is raised
     again so the job retries with backoff.
   - Because sync can repeat, storing items is an upsert.
4. **Connectors never see the database.** A connector gets the secret and the cursor and
   returns a batch of items and a new cursor, or "unchanged". The service does all the
   storing and auditing. One sync writes one audit event, with counts of added, updated
   and unchanged items.
5. **First connector: ICS calendar feeds.**
   - The feed URL is the credential, because Canvas, Google and Outlook put a private
     token in it.
   - Fetching uses only the standard library (`urllib`), over http or https only:
     - each socket operation has a 20 s timeout, the whole download has a 60 s deadline
       (so the single job worker cannot be stalled), and the size cap is 5 MB;
     - redirects are followed only to http or https;
     - a feed URL containing spaces or control characters is refused before any request.
   - Addresses on this PC or the LAN are allowed, which is fine for a single-user Hub.
   - It sends `If-None-Match` and `If-Modified-Since`, so a 304 writes nothing.
   - Error messages never contain the URL. They give an HTTP status or an exception type.
     Any other unexpected error, from any connector, is stored, logged and re-raised as
     "sync failed (<type>)" only. An exception's text can quote the URL, and a token in a
     URL path matches no redaction pattern.
6. **The ICS reader is our own (about 100 lines), no new dependency.** It handles folded
   lines (in linear time), a UTF-8 BOM, escapes, UTC times and all-day dates, checked
   strictly against the RFC formats. Nested blocks such as VALARM do not override the
   event.
   - A malformed time is flagged (`bad_time`), and the rest of the feed still syncs.
   - UIDs longer than 500 characters are stored by their SHA-256, so they stay distinct.
   - Recurrence rules are not expanded; they are flagged.
   - **Windows has no time-zone database without the `tzdata` package.** A `TZID` time
     keeps its raw value under `data.timezone_unresolved` and gets no start time.
   - Canvas feeds use UTC times and dates, so they are unaffected. Adding `tzdata` (a new
     dependency) is a question for the user.
7. **A deliberate design change during the card.** The first version had one global
   "check every minute" schedule. That wrote a job and its audit rows every minute even
   with nothing to sync, roughly 5,700 audit rows a day. Per-integration schedules cost
   nothing until something is connected.

## Consequences

- The email and Canvas REST connectors (later cards) are a `Connector` plus a credential.
  Each needs the user to choose the account and authorise it first.
- The morning brief can read upcoming items from `synced_item` across all sources.
