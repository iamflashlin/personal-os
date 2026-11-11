# 0021 — Always-on Hub: a per-user logon task, a supervisor, a separate runtime copy

- Status: accepted (the user asked on 2026-11-10 for the site to stay up without them
  starting it)
- Date: 2026-11-10
- Card: T-0016.

## Decisions

1. **A per-user scheduled task, "PersonalOS Hub".** It starts at the user's logon,
   hidden, needs no administrator rights, has no time limit and is retried by Task
   Scheduler. It is not a Windows service: a service would need admin rights and would
   run without the user's Credential Manager, which holds the Hub's secrets (ADR 0018).
2. **A supervisor script, `scripts/run/run-hub.ps1`.**
   - It starts `uv run --frozen python -m apps.hub` and starts it again 10 s after any
     exit.
   - It writes `logs/hub.log`, keeping one previous file of up to 10 MB, and records the
     Hub's process id in `hub.pid`.
3. **A separate runtime copy, `D:\dev\personal-os-run`.**
   - It is a git worktree detached at a chosen commit, with its own `.venv` and web
     build, so branch switches during development never touch the running Hub.
   - Running the installer again moves the copy to a new commit, rebuilds it and
     restarts the Hub.
   - The data lives in `D:\dev\personal-os-data`: on drive D (drive C is nearly full)
     and outside both trees.
4. **Installing is the user's action.** Claude Code's safety check refused to let the
   assistant register a logon task ("unauthorized persistence"), which is the right
   default for an agent. So the user runs `scripts/run/install-always-on.ps1` once.
   - `-PrepareOnly` builds the copy without registering anything; the assistant used it
     to test everything except the task itself.
   - `scripts/run/uninstall-always-on.ps1` removes the task and stops the Hub. The data
     stays, and `-RemoveCopy` also deletes the copy.

## 未验证

A real logoff/logon or reboot. Spike: after installing, sign out and in again, then open
http://127.0.0.1:8765 (≤ 5 min).
