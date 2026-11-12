# 0035: Fast lane for UI-only fixes

Status: accepted (2026-11-11). The user: "同意", after "每次都要怎么久?我都不用改进了，这么
一个小问题花了1小时".

## Context
ADR 0030 requires the reviewer's APPROVE on the exact head commit of every PR. For small UI
fixes this often meant two or three review rounds (25–40 minutes) for findings about
wording, tests or style, while the user waited. The biggest delay, however, was rework:
the panel shipped untried, and the user found that its groups could not be opened.

## Decision
- **Fast lane.** A PR gets one review when every changed file is under `apps/web/src/`,
  is `scripts/verify/web.py`, or is its own task card. The full rule applies if it also
  changes `apps/web/src/api.ts`, adds or changes a Hub endpoint call, renders HTML, or adds
  browser storage or third-party requests: those are privacy and security changes. The assistant fixes every blocking and should-fix
  finding, re-runs the gate and the web verification, and merges without a second round.
  Nits go to the next card.
- Everything else in ADR 0030 still holds for these PRs: CI green on both OSes, the PR
  targets main, exact-sha merge, and no `--admin`.
- Anything outside those paths uses the full rule. That covers contracts, the Hub,
  migrations, dependencies, credentials, privacy, permissions, CI and rules.
- **Try it first.** Before telling the user a page is ready, the assistant does the
  user's real task on the live Hub with the real data and looks at a screenshot.

## Consequences
- A small UI fix should take about 10–15 minutes instead of 25–40.
- A fix after the single review is not re-reviewed. The risk is limited to the web page,
  which renders mail as text only. A mistake there is visible and easy to revert, and the
  gate and the browser verification still run.
