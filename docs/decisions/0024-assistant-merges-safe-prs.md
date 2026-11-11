# 0024 - The assistant merges safe PRs; the user tries features instead of reading code

- Status: accepted; superseded in part by ADR 0030 (category exceptions removed)
- Date: 2026-11-11
- Supersedes: the "never merge PRs" rule in CLAUDE.md and the `gh pr merge` deny in
  ADR 0001's permission set

## Context

The user is new to programming and cannot judge a diff. Clicking "merge" on 22 stacked
PRs was a ritual, not a check. The checks that actually work are CI, the `reviewer`
subagent and the real verification scripts. The user asked (2026-11-11) for:
1. the assistant to merge PRs that pass those checks and touch nothing risky;
2. a plain-language 「给 Flash 看的」 section at the top of every PR;
3. a plain-language daily update in `docs/progress.md`.

## Decision

- The assistant runs `gh pr merge <n> --match-head-commit <sha> --squash` only when, for
  that head commit, every check passed on both OSes, the reviewer's latest verdict is
  APPROVE, the PR targets `main`, and `gh pr diff <n>` touches no database migration,
  permission/security rule, CI config or data-deleting code (concrete paths in
  CLAUDE.md). When unsure, the user merges. One condition is stricter than the user's
  request: "targets main" (see stacks below).
- `.claude/settings.json` allows `gh pr merge * --squash` (`--squash` last) and denies
  `--admin`, `--auto`, `--merge`, `--rebase`, branch deletion and `-R`/`--repo`. Other
  forms (`--squash` not last, `-s`, redirections) fall through to a prompt, which is
  fail-safe. The conditions themselves are enforced by CLAUDE.md, not by the permission
  system (it cannot read CI or the diff). `--match-head-commit` stops a merge of a commit
  pushed after the checks and the review.
- Every PR starts with 「给 Flash 看的」: what was done (≤3 plain sentences), yes/no
  questions with a recommendation, exact steps to try it, and who merges.
- Daily: a 「今天」 section at the top of `docs/progress.md`. `tools.report` overwrites the
  file today, so card T-0020 makes it keep that section.

## Consequences

- The user's role shifts from reading code to trying features and answering yes/no
  questions.
- Risk: a reviewer miss now reaches `main` without a human. Mitigations: the risky
  categories above stay manual, CI must be green, squash merges are one commit each and
  can be reverted with `git revert`.
- Squash-merging a stack breaks the PRs above it (their base commits disappear from
  `main`, and force-push to fix them is forbidden). So stacked PRs are not merged by the
  assistant; new cards branch from `main` once the previous one is merged. Every PR
  open on 2026-11-11 (#4-#25) and this one are stacked, so the user merges that backlog;
  the rule pays off from the next card on.
- Claude Code's own auto-mode safety check may still block a merge; then the user merges.
