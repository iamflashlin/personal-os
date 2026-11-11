# Personal OS

Personal AI execution system: the user states an intent, the system recalls personal
memory, prepares/does the work on the PC within granted permissions, and proves the
result with evidence. Full background: `docs/HANDOFF.md` (read the relevant section
when you need it; do not import it whole). It overrides `docs/source/` on conflict.
**What to build** follows the user's vision in `docs/VISION.md` (eight directions); HANDOFF
decides **how**. The roadmap realignment in `docs/decisions/0012-*` awaits the user.

## Commands

- Quality gate (must be green before any PR): `uv run python -m tools.check`
- Python tests only: `uv run pytest`
- Install deps after pulling: `uv sync` and `pnpm install`
- Real-behaviour verification: `uv run python scripts/verify/<module>.py`

## Architecture boundaries (see docs/HANDOFF.md §4)

- `apps/hub` (FastAPI modular monolith) is the only state owner (SQLite + file dir).
- `apps/desktop_agent` executes whitelisted actions and verifies them; it never plans
  and connects *out* to the Hub.
- `apps/web` is the PWA. `packages/contracts` holds every cross-process type; change
  contracts first, then both sides.
- Hub modules talk only via their `service.py` public functions and Pydantic types.
- Every table: ULID `id`, `owner_id`, UTC `created_at`/`updated_at`, `source`, `version`.
- Business code depends on `models.ModelProvider`, never on a vendor SDK directly.
- A task can never be marked done from model output alone; it needs an Evidence row.

## Task loop

1. Read the task card in `docs/tasks/` and related code; restate goal, constraints,
   dependencies. No `acceptance` section → do not start.
2. Stay inside the card's `allowed_paths`.
3. Write a failing test first when possible; bugs must be reproduced before fixing.
4. Run the quality gate, then the module's real verification script. Save outputs to
   `.evidence/<task-id>/` with a `summary.md` mapping each acceptance item to proof.
5. Ask the `reviewer` subagent to review the diff before opening a PR.
6. Branch per card (`t/0001-short-name`), Conventional Commits, PR to `main`.
   Never push to `main` directly (blocked by `.githooks/pre-push` and permissions).
7. Record decisions in `docs/decisions/NNNN-*.md`; repeated mistakes in
   `docs/lessons.md`, then turn them into a lint rule, test, type or hook.
8. Merge it yourself when the merge rule below allows; otherwise leave it for the user.
9. Once a day — at the end of the day's last session, or at the start of the next
   day's first session if it was missed — update `docs/progress.md`: a 「今天」 section
   at the top in plain Chinese (what got done, what waits for the user, what is next).
   Until card T-0020 makes `tools.report` keep that section, run `tools.report` first,
   then write 「今天」 by hand.

## Merging (ADR 0024)

The user does not read code; their check is trying the feature. You merge a PR with
exactly `gh pr merge <n> --match-head-commit <sha> --squash` (other forms prompt) only
when **all** of these hold for that head commit:
- every check in `gh pr checks <n>` passed on windows-latest and ubuntu-latest (none
  pending, failed or cancelled);
- the `reviewer` subagent's latest verdict on that exact diff is APPROVE;
- the PR targets `main` (not stacked on an unmerged branch);
- `gh pr diff <n> --name-only` touches none of:
  - database migrations: `apps/hub/migrations/**`;
  - permission or security rules: `.claude/**`, `CLAUDE.md`, `.githooks/**`,
    `apps/hub/credentials/**`, `apps/desktop_agent/token_store.py`,
    `apps/desktop_agent/config.py`, `apps/desktop_agent/actions/**` (the action
    whitelist), device pairing/auth, or anything that changes the security model;
  - CI config: `.github/**`;
  - deleting data: any code path that removes rows from the Hub database, or files from
    the Hub file dir or the user's PC.
If unsure whether a category applies, leave it for the user and say so in the PR's
「给 Flash 看的」 section. Never use `--admin`, never delete branches when merging.

## PR description

Every PR description starts with this section, before any technical detail:

```
## 给 Flash 看的
**做了什么**：(at most 3 sentences, everyday words, no jargon)
**要你拍板**：(yes/no questions, each with 推荐：是/否 and one reason; "无" if none)
**怎么试**：(exact steps: what to open or click, and what you should see)
**合并**：我会自己合并 / 需要你合并（原因）
```

The technical part (acceptance table, evidence, open questions, 我学到了什么) follows
below it; the user may skip it.

## Definition of done

Gate green locally and in CI (windows-latest + ubuntu-latest), real verification run
with evidence, reviewer findings resolved, PR starts with 「给 Flash 看的」 and includes
acceptance table, evidence summary, open questions, and a 3–5 sentence plain-language
"what I learned" in Chinese.
Your own report is never evidence; command output, screenshots and tests are.

## Never

- Read or write `.env*` files, print secrets, or put credentials in the repo or logs
  (use `keyring`).
- Force-push, push to `main`, merge PRs outside the merge rule above, delete
  branches/data, or deploy.
- Bypass git hooks (`--no-verify`, `-c core.hooksPath=...`, changing `core.hooksPath`).
- Install dependencies or system software, change system settings, or download
  without telling the user first. New dependency → note it in a decision record.
- Assume a tool is installed, or that the user has a Mac. Capabilities you have not
  verified are labelled "未验证" with a ≤half-day spike that would verify them.
- Add smart-home features or touch the user's other project ("定风台").
- Generate submittable homework answers for CIS course tasks (Human-led only).
- Write caches or large files to drive C (only ~11 GB free); use `D:\dev-cache`.

## Talking to the user

Chinese by default; code, comments and commit messages in English. The user is new to
programming: give every manual step as exact commands, one per line, saying what each
does. Only commands they must type go in code blocks; output to check goes in prose.
Stop and ask before: decisions that change architecture, data model or security
model; spending money, creating accounts or authorising third-party services;
deleting data, sending anything externally or other irreversible actions; acceptance
criteria that are ambiguous. Otherwise decide, give one default, explain in the PR.
