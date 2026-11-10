# Lessons

Repeated mistakes and how they were turned into automation. Format: date — what went
wrong — root cause — the check/test/hook/skill that now prevents it.

- 2026-11-10 — A GUI spike screenshot captured the user's own file — Win11 Notepad
  restores previous tabs on a blank launch — verify scripts act only on files/windows
  they create and capture only their own content control (ADR 0002). Not yet automated; convert into a
  shared helper in `scripts/verify/` during V0.1 S2.
- 2026-11-10 — `cmd /c "x & echo %ERRORLEVEL%"` reported exit 0 for a failing command —
  cmd expands `%ERRORLEVEL%` before running the line — record exit codes with
  PowerShell `$LASTEXITCODE` after the command.
- 2026-11-10 (open) — `subprocess.run(timeout=...)` on `pnpm.CMD` kills only cmd.exe; the
  node child can outlive a timed-out step — fix with a process-tree kill (`taskkill /T /F`)
  if a step ever hangs.
