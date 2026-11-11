# 0015 — Desktop agent core: process shape, exit codes, at-most-once executor

- Status: accepted (decided by Claude under ADR 0014, which the user accepted on
  2026-11-10; nothing here changes architecture, data model or the security model)
- Date: 2026-11-10
- Card: T-0007. Builds on ADR 0007 (the agent connects out) and ADR 0014 (protocol).

## Decisions

1. **One process, three commands.** `python -m apps.desktop_agent pair --code …` stores
   the token. `run` connects and serves actions. `forget` deletes the token. Pairing
   uses stdlib `urllib`, because `httpx` is a dev dependency only.
2. **Exit codes of `run`:**
   - 0: stopped.
   - 2: not paired.
   - 3: the Hub refused or revoked the token. Pair again.
   - 4: a newer agent replaced this one.

   On 3, the agent keeps the revoked token, so every later start also exits 3 until the
   user pairs again or runs `forget`. Deleting the token silently would turn a clear
   "revoked" into a vague "not paired".
3. **Reconnect.** Full-jitter exponential backoff: each wait is uniform in
   `[0, min(30 s, 0.5 s · 2^n)]`. The backoff resets only after a link stayed up for one
   heartbeat interval, so a Hub that welcomes and then closes at once is not redialled in
   a tight loop. The agent treats 3 heartbeat intervals of silence from the Hub as a dead
   link and reconnects. The Hub's interval is clamped to 0.2–300 s. A handshake that fails
   in any way other than HTTP 401/403 (for example a Hub that dies mid-handshake) is
   retried.
4. **Executor.**
   - Every desktop call runs on one worker thread, which the Windows adapter (T-0008)
     uses for COM.
   - An idempotency key runs at most once, even when two requests for it arrive at the
     same time.
   - A replay returns the first result, marked `replayed`.
   - The cache keeps the last 256 keys and evicts only finished entries.
   - Before anything touches the desktop, the agent re-checks the whitelist, the risk
     level and the params (defence in depth).
   - A timeout is reported as `failed`. Python cannot stop the stuck thread, so later
     actions wait behind it. The adapter's own calls are therefore bounded by the
     action's timeout, which is the smaller of the request's `timeout_s` and the
     whitelist's. The worker is a daemon thread, so a stuck call never blocks exit.
   - A replay answers under the new request's `action_id`.
5. **Results survive a dropped link, mostly.** A result that cannot be sent waits (up to
   100 of them; a warning is logged when the oldest is dropped) and goes out right after
   the next `welcome`. The Hub records a late result even for a run it marked `lost`
   (ADR 0014). Limit: `send()` returning means only that the bytes were buffered. A
   result sent just before the link drops can still be lost, because the protocol has no
   result acknowledgement; the run then stays `lost`. A `result_ack` message would close
   this gap and is a contract change for later.
   A timed-out action is reported `failed` with "it may still complete, check before
   retrying", because the handler may finish after the report.
6. **The desktop is behind `DesktopController`.** It has four calls: `open_url`, `which`,
   `spawn` (an argument list, never a shell) and `wait_for_window` (it polls titles and
   never focuses a window).
   - `load_controller()` imports `apps.desktop_agent.windows_adapter` (T-0008) lazily.
   - Until that module exists, every desktop call answers `needs_user`.
   - A missing `code` CLI also gives `needs_user`, and nothing is started.
7. **`keyring` is installed on every platform**, not only on Windows as ADR 0014 D1 said,
   because pyright on the Ubuntu CI runner must resolve the import. Its transitive
   dependencies: `jaraco.*` and `more-itertools` everywhere; `pywin32-ctypes` on Windows;
   `SecretStorage`, `jeepney`, `cryptography`, `cffi` and `pycparser` on Linux. Tests use
   an in-memory token store, so no Linux keyring backend is ever used.

## Spike R7 (keyring)

Unelevated `set_password` / `get_password` / `delete_password` under a unique service
name worked with the `WinVaultKeyring` backend and left no entry behind. The verify
script repeats this with a real paired agent on every run.

## Consequences

- T-0008 adds only `windows_adapter.py`, its spike and its real verification. The loop,
  the executor and the actions stay as they are.
- `scripts/verify/agent_link.py` proves the real process behaviour. It sends no action,
  so no window opens.
