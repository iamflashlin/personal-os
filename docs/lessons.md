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
- 2026-11-10 — Deleting a temp SQLite snapshot failed on Windows ("file in use"), and four
  more places leaked connections — `with sqlite3.connect(...)` only commits, it never
  closes — `tests/test_no_unclosed_sqlite.py` fails the gate on any such line; use
  `with closing(sqlite3.connect(...))` (ADR 0010).
- 2026-11-10 (open) — Evidence logs were captured before the last code edit, so the reviewer
  found them stale (T-0001, T-0003) — evidence was generated while work for the next card
  sat in the tree, and fixes came after the logs — park other cards' files outside the
  repo, regenerate every log as the last step, and state that in `summary.md`. Not
  automated yet: candidate check that each evidence log is newer than the newest
  tracked source file.
- 2026-11-10 (open) — A test that "proved" concurrent writes could pass without any write
  overlapping the export, and could hang forever if the writer died (T-0003 review) —
  the test asserted a value it had just read back — tests that rely on timing must assert
  the overlap happened and must have a deadline.
- 2026-11-10 — Chromium requested `/favicon.ico` and logged a 404 that unit tests never
  see (T-0004) — browsers fetch resources the page does not ask for —
  `scripts/verify/web.py` fails on any console error; the page declares an inline icon.
- 2026-11-10 — The first memory search index was keyed by SQLite rowid on a table whose
  primary key is a string, so VACUUM or a table rebuild could silently point search at the
  wrong rows (T-0005) — rowids of such tables are not stable — key derived tables by the
  real primary key; `test_search_does_not_depend_on_sqlite_rowids` moves every rowid, and
  `test_fts_triggers_exist_at_head` catches a rebuild that dropped the index triggers.
- 2026-11-10 — A LIKE `ESCAPE '\'` clause lost its backslash when edited through a shell
  heredoc, and no test covered the short-term search path (T-0005) — shell quoting
  rewrote the source, and tests only used wildcards in terms long enough for the FTS path —
  `test_short_terms_escape_like_wildcards`; edit backslash-heavy code with the editor,
  not with shell heredocs.
- 2026-11-10 — A test that expected lint-imports to fail passed for the wrong reason:
  the fake packages had a regular parent package, and lint-imports exited 1 before
  judging any contract (T-0006) — an exit code alone cannot tell "contract broken"
  from "tool crashed" — `tests/test_import_boundaries.py` asserts the report says
  `Contracts:` and names the BROKEN contract; check negative tests fail for the
  stated reason.
- 2026-11-10 — Claude reported VS Code as not installed and blocked T-0008 on it; the
  user had it at D:\Apps\VSCode (T-0008) — the search covered only default install
  folders and a shell whose PATH predated the install — before calling a tool missing,
  check the registry's Uninstall keys and the user PATH
  (`[Environment]::GetEnvironmentVariable("Path","User")`), not only `where`/`which`.
- 2026-11-10 — Four cards in a row (T-0006, T-0007, T-0010, T-0011) went to review
  without `.evidence/<card>/summary.md`, and each review blocked on it (T-0011) — the
  summary was written last, after fixing review findings — write `summary.md` together
  with the logs, before asking for review, and regenerate both after fixes.
- 2026-11-11 — The always-on installer reported "did not answer within 60 s" although
  the Hub was healthy (T-0016) — on Windows a venv's `python.exe` is a launcher, so the
  process owning the port runs from the base Python and only its parent is in the copy;
  the earlier test happened to see the launcher path — the installer and
  `scripts/verify/always_on.py` check the listener and its parent; when identifying a
  Python process on Windows, look at the parent process too.
- 2026-11-11 — A shell heredoc again ate the backslashes of a regex edit (T-0020, T-0022),
  despite the 2026-11-10 lesson — the "patch script in a heredoc" habit made the same
  mistake one level down — edit regex and other backslash-heavy code only with the editor
  tool or a script file written by the editor, never through a heredoc.
- 2026-11-11 — A spike "proved" LiteLLM does not follow redirects, but it did; the
  reviewer caught it (T-0024) — the stub only answered POST, so the redirected GET got a
  501 and was never recorded, and a missing request looked like a refused redirect — stubs
  used to prove that something did not happen must record every method and path, and a
  negative test must be shown to fail when the protection is removed.
- 2026-11-11 — Summaries failed on real mail although every test passed (T-0025 → T-0026):
  DeepSeek reasoned on its own and spent all max_tokens, which ADR 0025 had listed as
  未验证 but nobody ran a live check before shipping a new prompt — the stub never models
  hidden reasoning — before switching a live prompt, run one live call on a realistic,
  link-heavy fake email and check finish_reason and token use; switch vendor reasoning off
  unless a task needs it.
