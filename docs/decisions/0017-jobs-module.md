# 0017 — Jobs: SQLite queue, one in-process worker, at-least-once delivery

- Status: accepted (decided by Claude; HANDOFF §4.3 and §5 already chose "SQLite job table +
  worker", so no architecture, data-model or security choice is new here)
- Date: 2026-11-10
- Card: T-0010. Needed by the email and Canvas integrations, which the user asked to build
  after the foundations (2026-11-10).

## Decisions

1. **Two tables.**
   - `job`: kind, payload, status, attempts, max_attempts, `run_at`, an optional
     `idempotency_key` (unique per owner) and `last_error`.
   - `job_schedule`: one row per owner and kind, with `interval_s` and `next_run_at`.
   - Both use the `Entity` mixin, so they carry an owner, timestamps, a source and a
     version.
2. **Statuses.** `queued → running → succeeded`. A failed attempt goes back to `queued`
   with `run_at` pushed back. After `max_attempts` (default 5) the job is `dead`. A kind
   that has no handler is `dead` at once. Only a person moves a dead job back, with
   `POST /jobs/{id}/retry`, which grants a fresh set of attempts.
3. **Backoff.** Each retry waits `base · 2^(attempt-1)`, capped at one hour. `base` is
   `POS_JOBS_RETRY_BASE_S`, 5 s by default.
4. **At least once, not at most once.** A job cut off by a crash is still `running` at the
   next start, and is queued again after the usual backoff (`requeue_interrupted`).
   Handlers must therefore be idempotent, for example "fetch mail newer than the stored
   cursor". This is the opposite of desktop actions (ADR 0014), where repeating a click
   could do harm.
   - The cut-off attempt counts. A job that keeps killing the Hub becomes `dead` after
     `max_attempts` restarts, instead of looping forever.
   - The worker also runs this recovery at the start of every pass. Jobs run one at a
     time, so a job still `running` there is one whose ending could not be recorded (for
     example a locked database), and it is recovered without waiting for a restart.
5. **Schedules.**
   - Each due schedule enqueues one job whose key names its slot
     (`schedule:<kind>:<slot time>`), so a slot can never produce two jobs.
   - Slots missed while the Hub was down collapse into one catch-up run.
   - `ensure_schedule` writes nothing when the schedule already matches, so modules can
     call it on every start. A shorter interval takes effect at once.
   - One schedule that fails to fire (it is audited) does not stop the others or the
     queue.
6. **One worker.**
   - An asyncio task in the Hub process polls every `POS_JOBS_POLL_S` (1 s) and runs
     handlers in a thread, one at a time.
   - The single worker is possible because the Hub already runs one uvicorn process
     (ADR 0014).
   - On shutdown the loop is cancelled at once. A handler still in its thread cannot be
     stopped, so its job stays `running` (decision 4 covers it), and Python waits for that
     thread before the process exits. A slow sync can therefore delay a Ctrl-C. Handlers
     with a time budget or a cancel flag are a later improvement.
7. **Kinds are wired in `main.job_kinds()`.** Modules contribute handlers there and never
   import each other. A handler receives the engine and the `Job`.
8. **No public "create job" endpoint.** HTTP clients can only list, read and retry. Jobs
   come from Hub modules, which keeps the local attack surface the same (ADR 0014 D4).
9. **Audit.** Enqueue, start, finish, requeue, retry and schedule changes each write one
   audit event. A job made by a schedule is recorded by the schedule's `fire` event,
   which names the job, not by a separate `enqueue` event. Payloads and errors pass
   through redaction. A handler's error is redacted once, before it is logged, stored
   in `last_error` or audited. Payloads are stored as given, so secrets must never be put in them:
   credentials belong in the credential store (T-0011).

## Consequences

- Integrations become "a handler plus `ensure_schedule`" (T-0012).
- A periodic job writes a few audit events per run. At one sync every 15 minutes that is
  a few hundred rows a day. Pruning old jobs and their audit events is a later card.
