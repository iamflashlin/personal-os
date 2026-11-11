# 0014 — Desktop agent link: pairing, WebSocket protocol, at-most-once actions (PROPOSAL)

- Status: **accepted (user, 2026-11-10: "全部按推荐", all defaults D1–D5)**. Implementation starts with T-0006.
- Date: 2026-11-10
- Cards: T-0006 (contracts + Hub), T-0007 (agent core), T-0008 (Windows adapter + real
  verification). HANDOFF S2; VISION direction 3 (数字世界的执行者).
- Drafted by the `architect` subagent from HANDOFF §4.1–§4.6, §8.2–§8.3, ADRs 0002, 0005,
  0007 and 0011, and the code on `t/0005-memory`.

## Findings that shape the design

1. **uvicorn 0.54 in uv.lock cannot serve WebSockets.** Its only dependencies are `click`
   and `h11`; there is no `websockets` or `wsproto`. A real Hub would refuse every upgrade,
   and only Starlette's TestClient would work. A new runtime dependency is therefore
   unavoidable (D1).
2. **The boundary test keys contracts by type.** `tests/hub/test_module_boundaries.py`
   would silently pick the wrong contract once a second `independence` contract (hub vs.
   agent) is added. T-0006 changes it to key by contract name.
3. **Screenshots versus ADR 0002.** `os.startfile(url)` usually opens a tab in the user's
   existing browser window, which S2 must not force to the foreground. A screen-region grab
   could then capture whatever covers it (D5).

## Proposed design (summary)

**Contracts** (`packages/contracts/actions.py`, `devices.py`, `agent_protocol.py`):
- `RiskLevel` P0–P4. `ActionName` = `open_url`, `open_folder_in_editor`. An `ActionSpec`
  registry holds params, risk, reversible and timeout; both actions are P1.
- `ActionRequest` / `ActionResult` with an `idempotency_key` and `evidence[]` (kinds:
  window, note).
- `open_url` accepts only `http`/`https`, plus a required `expect_title_contains`.
- `open_folder_in_editor` takes an absolute path and refuses cmd metacharacters (the
  `code.cmd` argument-injection class).
- Pairing code: Crockford base32, 40 bits, valid 5 minutes, one-time.
- Token: prefix `posd_`, so redaction catches it. Only its SHA-256 is stored.
- WebSocket envelope `v: 1`:
  - agent → Hub: `hello`, `heartbeat`, `action_result`;
  - Hub → agent: `welcome`, `heartbeat_ack`, `action_request`;
  - close codes: 4401 revoked, 4408 heartbeat timeout, 4409 replaced by a newer agent,
    1008 protocol error.

**Hub:**
- Modules `devices` (pairing, tokens, an in-memory connection registry, `/agent/ws`) and
  `actions` (dispatch and results). Tables `device`, `pairing_code` and `action_run`, with
  a unique `(owner_id, idempotency_key)`.
- Authentication on the handshake: `Authorization: Bearer <token>`. Any `Origin` header is
  refused before `accept()`, because browsers always send Origin and our agent never does.
- Every write is audited.
- Heartbeats live only in memory and are not audited.
- One uvicorn worker, because the registry is in-process.

**At-most-once:**
- The `action_run` row is committed before the frame is sent. A replayed POST returns the
  stored run and never contacts the agent.
- **The Hub never redelivers.** A missing result becomes `lost`, not a retry.
- The agent also keeps an in-memory cache (256 keys) as defence in depth. It needs no
  durable state, apart from its token in keyring.

**Agent** (`apps/desktop_agent`):
- Connects out with jittered exponential backoff (max 30 s), and stops on 401, 403 or
  4401 (re-pair) and on 4409.
- One worker thread runs every desktop call; it also owns COM for pywinauto.
- `DesktopController` protocol, with `WindowsAdapter` in T-0008.
- `verify()` polls UIA window titles and never requires the foreground.
- A missing `code` CLI gives `needs_user`. Nothing is installed.
- Import contract: `apps.hub` and `apps.desktop_agent` never import each other.
  `packages.contracts` imports neither of them.

**Verification (T-0008):**
- The script serves its own page with a unique marker title, and counts page-load beacons
  (not GETs) to prove a single execution.
- It closes only the window it created; the page closes itself.
- It never sends keystrokes and never closes the user's browser window.

## Decisions for the user (each with Claude's default)

- **D1: new dependencies.**
  - `websockets`: required, for the uvicorn server side and the agent client.
  - `keyring`, Windows only, to keep the agent token in Windows Credential Manager, as
    HANDOFF §4.6 already chose.
  - Declare the already-locked `pywin32` explicitly, because T-0008 imports `win32gui`.
  - Default: yes. If you say no to `keyring`, the agent uses pywin32's `win32cred`, which
    needs no new package.
- **D2: offline behaviour in S2.** HANDOFF §4.5 queues commands while the PC is offline;
  the S2 acceptance does not require it.
  - Default: no queue yet. `POST /actions` returns 503 "agent offline" without consuming
    the key, and `GET /agent/status` shows offline. The queue comes with the jobs module.
- **D3: `launch_app`.** Which apps it may launch is a product choice, and some apps (for
  example Notepad) restore the user's private content (ADR 0002).
  - Default: leave it out of S2. Add it in S3 with a whitelist taken from user-confirmed
    `Workspace.apps`.
- **D4: security gap until S8.** Any local process could create a pairing code and send P1
  actions (open an http/https URL, or open a folder in VS Code). This extends the gap in
  ADR 0011 §3.
  - Default: accept it until S8, because of these limits:
    - loopback bind and TrustedHost;
    - JSON body plus a required `Idempotency-Key` header, which blocks browser
      cross-origin calls;
    - Origin refused on the WebSocket;
    - P2 and above hard-refused.
  - S4 must add authentication to these endpoints before the Hub binds to Tailscale.
- **D5: screenshot method for the S2 evidence.**
  - Default: capture the browser window into memory with `PrintWindow`, crop to our page's
    UIA Document control, and save only the crop. The window is never focused.
  - Fallback, if the spike fails or you prefer it: capture only while you have brought the
    browser to the front yourself.

## Risks and unverified items (each a spike of at most half a day)

| # | Item | Spike |
|---|---|---|
| R1 | uvicorn 0.54 plus `websockets` serves `/agent/ws`. A pre-accept refusal reaches the client as HTTP 403 and a post-accept 4401 as the close code. `ws="auto"` may warn | ~1 h minimal app plus client with `-W error::DeprecationWarning` |
| R2 | `PrintWindow(PW_RENDERFULLCONTENT)` returns real pixels for a covered browser window | ½ day `spike_printwindow.py` |
| R3 | The default browser and its title format; whether `window.close()` can close a ShellExecute tab | ~2 h |
| R4 | `code` on PATH, the new-window title format, Workspace Trust, and VS Code restoring the user's previous windows on cold start | ~2 h on this PC |
| R5 | pywinauto UIA from a worker thread needs COM initialised in that thread | ~1 h |
| R7 | keyring works unelevated and leaves nothing behind under a unique service name | 30 min |
| R8 | TestClient POST from a second thread while a WebSocket is open | 1 h; fallback: an in-thread uvicorn server |
| R9 | An import-linter independence contract across two root packages of the `apps` namespace | 15 min |
| R12 | A 40-bit pairing code without an attempt limit is acceptable only on loopback | before S4: invalidate codes after 10 failed attempts in 5 min |

## User decisions (2026-11-10)

The user accepted every default, after a plain-language explanation:

- **D1:** add `websockets` and `keyring` (Windows only), and declare `pywin32`.
- **D2:** no offline queue yet. An offline agent gives 503 "agent offline".
- **D3:** leave `launch_app` out of S2.
- **D4:** accept the local-only security gap until S8. Authentication is required before
  the Hub binds to Tailscale (S4).
- **D5:** screenshots capture only our own page, never the screen or the tab strip.

## Consequences

- T-0006, T-0007 and T-0008 are unblocked and are done in that order.
