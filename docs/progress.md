# 进度报告

<!-- today:start -->
## 今天

2026-11-11

- **做完了**：Hub 现在开机就在后台运行，崩溃后会自己重启。之前积压的二十多张卡已经全部合进正式版本，只剩“Windows 窗口操作”那一张（T-0008）。以后安全的改动由 Claude 自己合并，每个 PR 最上面都有给你看的大白话。
- **等你**：在 GitHub 上把 #15（T-0008）的合并目标改成 main，然后合并它。#9 到 #24 里除了 #15，其余都已经被 #27 代替，可以关掉。
- **下一步**：等你说一下作息时间（几点起床、上课、睡觉），就能开始做每日简报和定时提醒。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-11` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ 16a3d05（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 29 张任务卡：已完成 25，进行中 0，待审核 1，卡住 0，未开始 3。

### 已完成

- **D0-01** Repository skeleton, uv + pnpm, tools.check quality gate, CI
- **D0-03** CLAUDE.md, permission rules, architect/reviewer/tester subagents, .mcp.json
- **D0-05** Spike - open Notepad, screenshot, read title via pywinauto, close
- **D0-06** ARCHITECTURE.md and ADRs for modular monolith, SQLite, agent-initiated connection
- **D0-07** tools/report.py generates docs/progress.md from task cards and git log
- **D0-08** Record the product vision, propose a realigned roadmap, and housekeeping
- **D0-10** Assistant merges safe PRs; plain-language PR summary and daily progress
- **T-0001** Hub skeleton - FastAPI app, settings, SQLite (WAL) + Alembic, base model, boundary check
- **T-0002** Goal / Project / Task / Workspace CRUD API with audit log
- **T-0003** pos export / pos import v0 with round-trip migration test
- **T-0004** Minimal web UI - list goals/projects/tasks, create a task, confirm a task done
- **T-0005** Second brain v0 - Memory entries with provenance, correction, expiry and full-text search
- **T-0006** Action contract and Hub side of the desktop agent link - pairing, token, WebSocket, heartbeat, idempotent dispatch
- **T-0007** Desktop agent core - connect out, reconnect with backoff, whitelist registry, at-most-once executor
- **T-0009** Memory page in the web UI - search, add, correct, confirm, delete
- **T-0010** Jobs module - SQLite job queue, in-process worker, retries with backoff, interval schedules
- **T-0011** Credential store - integration secrets in Windows Credential Manager, metadata only in SQLite
- **T-0012** Integrations framework - accounts, sync through jobs, idempotent synced items, ICS calendar-feed connector
- **T-0013** Connections page in the web UI - add a calendar feed, see sync status, upcoming 14 days
- **T-0014** Add tzdata so calendar events in named time zones get exact times on Windows
- **T-0015** Canvas connector - courses, assignments (due, points, submitted) and announcements through the Canvas REST API
- **T-0016** Always-on Hub - runs in the background from login, restarts after a crash, separate from development
- **T-0017** Prune synced items a complete sync no longer returns (deleted assignments, cancelled events)
- **T-0018** Email connector (IMAP, read-only) - 163 now with its 授权码, Gmail later, same connector
- **T-0019** 今日 page - one view of today's deadlines, missing work, events, unread mail and news

### 待审核

- **T-0020** progress.md keeps a hand-written 「今天」 section and counts merge-commit PRs

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules
- **T-0008** WindowsAdapter and real local verification - open a test URL and a temp folder, verify windows, prove one execution per key

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-09 至 2026-11-15）

本周合并了 25 张任务卡：D0-01, D0-03, D0-05, D0-06, D0-07, D0-08, D0-10, T-0001, T-0002, T-0003, T-0004, T-0005, T-0006, T-0007, T-0009, T-0010, T-0011, T-0012, T-0013, T-0014, T-0015, T-0016, T-0017, T-0018, T-0019。

- 2026-11-11 chore(claude): assistant merges safe PRs, plain-language PR summary (D0-10) (#26)
- 2026-11-11 Merge pull request #27 from iamflashlin/t/stack-catchup
- 2026-11-11 feat(hub): pos export / pos import with checksummed packages (T-0003) (#7)
- 2026-11-11 feat(tools): progress report from task cards and merges (D0-07) (#6)
- 2026-11-11 docs: ARCHITECTURE.md and ADRs 0005-0007 (D0-06) (#5)
- 2026-11-11 chore(claude): allow pushing feature branches and opening PRs (#4)
- 2026-11-10 feat(hub): goal/project/task/workspace CRUD with audit log (T-0002) (#3)
- 2026-11-10 feat(hub): add Hub skeleton with migrated SQLite and boundary checks (T-0001) (#2)
- 2026-11-10 chore: bootstrap D0 dev factory (D0-01, D0-03, D0-05) (#1)

## 返工

以 `fix:` 开头、修的是之前已经合并过的任务卡的提交：

- （没有）

## 我能看到什么

**Hub 的接口文档页：能看到并试用所有接口**

1. `uv run python -m apps.hub`
2. 浏览器打开 http://127.0.0.1:8765/docs

**网页界面：看目标、项目、任务，新建和确认完成任务；在“记忆”页搜索和管理记忆**

1. `pnpm --dir apps/web build`
2. `uv run python -m apps.hub`
3. 浏览器打开 http://127.0.0.1:8765/
