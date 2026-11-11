# 0001 — Claude Code project configuration (D0-03)

- Status: accepted
- Date: 2026-11-10
- Checked against: code.claude.com/docs/en/{settings, permissions, settings-reference,
  sub-agents, mcp, memory, plugins/marketplace-reference} on 2026-11-10.

## Context

HANDOFF.md §7.2 sketched `CLAUDE.md`, `.claude/settings.json`, `.claude/agents/*.md`
and `.mcp.json`. This machine runs native Windows with no sandbox, and Claude Code's
primary shell here is the **PowerShell** tool.

## Findings and corrections vs. HANDOFF §7.2

| # | HANDOFF §7.2 | Official docs say | What we did |
|---|---|---|---|
| 1 | Only `Bash(...)` rules | PowerShell rules have their own specifier, `PowerShell(...)`, "same shape as Bash rules", case-insensitive, aliases canonicalised | Every allow/ask/deny rule exists in both `Bash(...)` and `PowerShell(...)` form |
| 2 | `deny: Bash(git push --force *)` | Argument-constraining rules are "fragile" and "not a security boundary"; `git -C . push ...` slips past `Bash(git push *)` | Deny `--force`/`-f` in any position, `--no-verify`, pushes naming `main` (`* main`, `*:main*`, `*+main*`), remote branch deletion (`--delete`, `* :*`), local `git branch -d/-D`, and changing/overriding `core.hooksPath`. Real enforcement for "never push to main" is the versioned `.githooks/pre-push` hook (see below), not permission rules |
| 3 | `deny: Bash(rm -rf *)` | Same fragility; on Windows the usual form is `Remove-Item -Recurse` | `PowerShell(Remove-Item * -r*)` / `Remove-Item -r*` (aliases `rm`/`del`/`ri` canonicalise to `Remove-Item`; `-r*` covers `-Recurse`), `cmd /c rd|rmdir`, Bash `rm -r*`/`-R*`/`-f*`/`--recursive*`, `git clean`, `git reset --hard`. `rm -f*` also blocks single-file deletes; accepted (errs safe) |
| 4 | `Read(./.env)`, `Read(./.env.*)` | `./` = current dir only. Read denies also cover Bash `cat/head/tail/sed` but not scripts or `grep -r` | Use `Read(**/.env)`, `Read(**/.env.*)`, `Edit(**/.env)`, `Edit(**/.env.*)` (any depth; Edit also covers Write) plus `PowerShell(Get-Content *.env*)`. Side effect: `.env.example` is also unreadable by Claude; acceptable, the user edits it |
| 5 | No `ask` list | `permissions.ask` is supported; order is deny → ask → allow | `git push`, `gh pr create`, `uv add`, `pnpm add` always prompt |
| 6 | pstack in settings "to be decided" | `enabledPlugins` keys are `<plugin>@<marketplace>`; `extraKnownMarketplaces` is a map of name → `{ "source": {...} }`; github sources use `repo` | Kept `enabledPlugins: {"pstack@cursor-plugins": true}`, added `extraKnownMarketplaces.cursor-plugins.source = {source: github, repo: cursor/plugins}` (same shape Claude Code wrote to `~/.claude/plugins/known_marketplaces.json`). Applies only after the user trusts the folder |
| 7 | reviewer: `tools: Read, Glob, Grep, Bash` called "read-only" | Bash can write; `disallowedTools` removes tools; omitting `tools` inherits all | reviewer gets `disallowedTools: Edit, Write, NotebookEdit` and a prompt limited to read-only commands; shell writes still hit the normal permission prompt, except via allowed commands: `git diff/log --output=<file>` can write a file (accepted risk; low impact). `ruff` is allowed only as `check` / `format --check`. architect gets only Read/Glob/Grep (truly read-only) |
| 8 | `model: opus` | Valid values: `sonnet`, `opus`, `haiku`, `fable`, full ID, `inherit` | reviewer/architect `opus`, tester `inherit` |
| 9 | `.mcp.json` with `@playwright/mcp@latest` | `type: stdio` is valid (and default). No Windows `cmd /c` note in docs | Pinned `@playwright/mcp@0.0.84` with `-y`. Plain `npx` works on this machine (`claude mcp list` → Connected), so no `cmd /c` |
| 10 | CLAUDE.md "under 100 lines", no `@` import of HANDOFF | Docs target < 200 lines; imports don't save context | CLAUDE.md is ~70 lines and points to HANDOFF by path |
| 11 | Project `allow` rules | Shared-project `allow` waits for folder trust; `deny`/`ask` apply immediately | No change; noted for new machines |

## Protecting `main` without paid branch protection

Branch protection / rulesets on a **private** repo likely need a paid GitHub plan
(unverified; steps to check are in the PR). Decision (user, 2026-11-10): all changes go
through PRs, and direct pushes to `main` are blocked locally by:

1. `.githooks/pre-push` rejects any push whose remote ref is `refs/heads/main`.
   Enabled per clone with `git config core.hooksPath .githooks` (in `docs/SETUP.md`).
2. Permission denies on pushes naming `main`, `--no-verify`, and edits to `core.hooksPath`.
3. `gh pr merge` is denied for Claude; only the user merges, in the GitHub UI.

Limit: a hook can be bypassed with `--no-verify`, which CLAUDE.md forbids and the
permission rules deny (best-effort). `tools.check` warns locally when `core.hooksPath`
is not `.githooks`. If the plan allows it later, add a GitHub ruleset as the server-side
guard.

## Amendment 2026-11-10: feature-branch pushes and PR creation allowed

User decision. Claude may now push feature branches and open PRs without a prompt:

- `allow`: `git push -u origin t/*`, `git push -u origin d0/*`, `gh pr create *`
  (Bash and PowerShell).
- Removed from `ask`: `git push *` and `gh pr create *`. Because `ask` beats `allow`,
  they would otherwise still prompt. Any other push still prompts, because it matches
  no allow rule.
- Unchanged: every `deny` (pushes naming `main`, `--force`/`-f`, `--no-verify`,
  `--delete`, `core.hooksPath` edits, `gh pr merge`), the `.githooks/pre-push` hook, and
  `uv add` / `pnpm add` in `ask`. `deny` beats `allow`, so `git push -u origin t/x --force`
  is still refused.

## Consequences

Two parallel rule sets (Bash + PowerShell) must be kept in sync; a future check could
assert that. Permission rules reduce accidents but are not a sandbox.
