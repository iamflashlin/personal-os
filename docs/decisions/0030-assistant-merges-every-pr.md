# 0030 - The assistant merges every PR and updates the always-on Hub

- Status: accepted (the user, 2026-11-11)
- Supersedes: the category exceptions in ADR 0024 (migrations, permission/security rules,
  CI, data deletion), and the user's own manual step after each merge in ADR 0021.

## Context

ADR 0024 let the assistant merge only PRs that touched nothing risky. In practice almost
every PR touched a migration, CI or a rule file, so the user still clicked merge, without
reading the code. Every merge was then followed by the user running the installer to
update the always-on Hub. On 2026-11-11 the user said: "PR你不能自己合并吗……接下来都你自己合并".
Asked whether to keep one exception for PRs that change the assistant's own rules, the
user chose "全部由我合并，没有例外" (the assistant merges everything, no exceptions). For
updating the Hub, the user chose an update-only script that is allowed in the permission
rules.

This PR is the last one the user merges by hand. It changes `CLAUDE.md` and
`.claude/settings.json`, and the assistant should not give itself these rights.

## Decision

- **Merging.** The assistant merges every PR with
  `gh pr merge <n> --match-head-commit <sha> --squash` once, for that head commit:
  - every check passed on both OSes;
  - the reviewer's latest verdict on that exact diff is APPROVE;
  - the PR targets `main`.

  Nothing is excluded by category. Quality gates stay as they are. For migrations, new
  dependencies, CI and rule changes, the PR's 「给 Flash 看的」 says plainly what changed, so
  the user can object after the fact. `--admin`, branch deletion and merging with a red
  check stay forbidden, both in the rules and as permission denies.
- **Updating the Hub.** New `scripts/run/update-hub.ps1`. It takes no path or ref, so
  the allowed command cannot run an unreviewed branch or touch another folder. It:
  - fetches origin/main first, because a merge on GitHub does not move the local `main`;
  - stops the supervisor and Hub (only processes proven to be ours);
  - refuses to continue if something else holds port 8765;
  - moves the runtime copy to origin/main, installs packages from the local cache and
    builds the page. If any step fails, it moves the copy back to the previous commit and
    re-syncs it;
  - starts the existing "PersonalOS Hub" task again;
  - reports `Hub is up` only when the Hub on port 8765 runs from the copy.

  `-Check` runs only the preflight and stops nothing. The script never creates or changes
  the scheduled task. That stays the user's one-time install (ADR 0021), because Claude
  Code's safety check refuses to let the assistant set up anything that persists. A
  commit that changes `run-hub.ps1`'s parameters still needs the installer re-run.
  `.claude/settings.json` allows exactly the argument-free command, with no wildcard.

## Consequences

- From the next PR on, the user's role is to try features and answer the yes/no questions.
- Risk: the assistant can now merge changes to its own rules. Mitigations:
  - every such PR still needs green CI and a reviewer APPROVE;
  - its 「给 Flash 看的」 must say that it changes rules;
  - git history keeps every change revertable;
  - the `main` branch push block (`.githooks/pre-push`) and the deny list are unchanged.
- If Claude Code's auto-mode safety check still refuses `update-hub.ps1`, the assistant
  says so and gives the user the one command to run.
