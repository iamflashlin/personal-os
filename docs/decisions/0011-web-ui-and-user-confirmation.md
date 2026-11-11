# 0011 — Minimal web UI, and user confirmation as the first kind of Evidence

- Status: accepted (made autonomously; the user asked for decisions to be recorded)
- Date: 2026-11-10
- Task: T-0004

## Context

The user asked for a page in the PC browser that lists goals, projects and tasks, can
create a task, and can **mark a task done**. CLAUDE.md says a task can never be marked
done from model output alone: it needs an Evidence row. In T-0002 every move to `done`
was therefore refused (409), because Evidence did not exist yet.

## Decisions

1. **The smallest Evidence that serves the request.** A new Hub module `evidence` owns
   an `evidence` table (migration 0003). It has one kind, `user_confirmation`: a person
   pressed "确认，我已完成" in a UI, optionally with a note. Build/test output, commits
   and files stay in S6 (HANDOFF §3 item 5 already lists user confirmation as a kind).
2. **One way to reach `done`.** `POST /tasks/{id}/complete` with `{version, note}`. In
   one transaction it writes the Evidence row, sets `status=done` and adds one audit event
   (`task.complete`, with the evidence id). A stale version or an already-done task
   returns 409. `PATCH status=done` is still refused, and a done task cannot be
   reopened (409), so its Evidence never describes a task that is no longer done. `GET /tasks/{id}/evidence` lists
   the proof. A task with evidence cannot be deleted (409), so the proof cannot vanish.
3. **Known gap: the Hub cannot yet tell a human click from any other HTTP client.**
   - The Hub binds 127.0.0.1 by default (`POS_HUB_HOST` can widen it) and has no auth
     until S2/S8. A local script or a future agent could call `/complete`.
   - Every Evidence row records `source="api"`, so a row cannot yet show which client
     wrote it.
   - Because the Hub now serves a web page, a malicious site could try DNS rebinding
     (pointing its own domain at 127.0.0.1) to call the API from the user's browser.
     `TrustedHostMiddleware` closes that: any Host other than `127.0.0.1`, `localhost`
     or the configured `POS_HUB_HOST` gets 400 (tested). A wildcard bind such as
     `0.0.0.0` is not added, and IPv6 `[::1]` is not allowed yet; LAN/Tailscale access
     (S4) must list its real host name. The page makes idempotency keys with
     `crypto.randomUUID` and falls back to `getRandomValues` on non-secure origins. Form-based CSRF does not apply,
     because the API only accepts JSON bodies.
   - Follow-up (S8): `/complete` must require a grant that the desktop agent and the
     planner do not have, and Evidence should record the device or session that wrote it.
4. **The Hub serves the built UI.** `pnpm --dir apps/web build` writes `apps/web/dist/`
   (gitignored). When it exists, `create_app` mounts it at `/` after all API routes, so
   one process and one address serve both. No CORS setup is needed. `pnpm --dir apps/web
   dev` (port 5173, proxying the API to :8765) is there for UI work.
5. **The UI is a thin client.** It keeps no state of its own (ARCHITECTURE B1/B8). The
   TypeScript types in `apps/web/src/api.ts` are hand-written to match
   `packages/contracts`. Generating them from `openapi.json` is S4.
6. **Verification drives the installed Microsoft Edge through Playwright for Python**
   (`channel="msedge"`). Windows 11 ships Edge, so no browser download is needed and
   nothing is written to drive C. Screenshots show only the page in a browser the script
   launched (ADR 0002 rule).
7. **Desktop browser only**, Chinese labels, light and dark colour schemes. Phone layout
   and offline support are S4.

## New dependencies

| Dependency | Where | Why |
|---|---|---|
| react 19.3.1, react-dom 19.3.1 | `apps/web` (pnpm workspace) | UI (HANDOFF §4.8) |
| vite 8.3.7, @vitejs/plugin-react 6.3.0 | `apps/web` dev | build and dev server (HANDOFF §4.8) |
| @types/react 19.3.0, @types/react-dom 19.3.0 | `apps/web` dev | type checking |
| playwright 1.65.0 (Python), with greenlet 3.5.6 pulled in transitively | uv `dev` | `scripts/verify/web.py` drives Edge |

`pnpm-workspace.yaml` adds `apps/web` as a workspace package. The root `tsconfig.json`
gains `jsx: react-jsx` and the DOM libs, so `tools.check` type-checks and tests the UI.
The pnpm store stays on `D:\dev-cache\pnpm-store`.
