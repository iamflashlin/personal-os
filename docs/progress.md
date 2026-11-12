# 进度报告

<!-- today:start -->
## 今天

2026-11-11

- **做完了**：
  - 邮件接上了 AI（DeepSeek）：每封邮件都有一句话标题、重要程度和要点，验证码这类邮件不会发给 AI。
  - 全部历史邮件已补到 356 封（最早到 2 月），每封只总结一次，本月只花了约 0.20 美元，每月上限 10 美元。
  - 没价值的邮件不再收起来，和其他邮件按时间一起排，只标“次要”。
  - 后台加了“看门狗”：Hub 被意外关掉后，最多 5 分钟自己恢复。
  - 今天一共合并了 #15、#28 到 #39。
- **等你**：
  - 运行一次 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run\install-always-on.ps1`，让看门狗生效。
  - 回答一个问题：问邮件时，你的问题和邮件总结会发给 DeepSeek，可以吗？你同意后，问答功能（#40）才会合并。
- **下一步**：
  - 问答功能上线：“邮件”页顶部会有提问框（T-0031），已经做好，正在审查。
  - 然后做批量规则（要先请你确认），以及 Canvas 截止日期变动提醒。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-11` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ 4daf4f4（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 39 张任务卡：已完成 37，进行中 0，待审核 0，卡住 0，未开始 2。

### 已完成

- **D0-01** Repository skeleton, uv + pnpm, tools.check quality gate, CI
- **D0-03** CLAUDE.md, permission rules, architect/reviewer/tester subagents, .mcp.json
- **D0-05** Spike - open Notepad, screenshot, read title via pywinauto, close
- **D0-06** ARCHITECTURE.md and ADRs for modular monolith, SQLite, agent-initiated connection
- **D0-07** tools/report.py generates docs/progress.md from task cards and git log
- **D0-08** Record the product vision, propose a realigned roadmap, and housekeeping
- **D0-10** Assistant merges safe PRs; plain-language PR summary and daily progress
- **D0-12** Assistant merges every PR; update-only script for the always-on Hub
- **T-0001** Hub skeleton - FastAPI app, settings, SQLite (WAL) + Alembic, base model, boundary check
- **T-0002** Goal / Project / Task / Workspace CRUD API with audit log
- **T-0003** pos export / pos import v0 with round-trip migration test
- **T-0004** Minimal web UI - list goals/projects/tasks, create a task, confirm a task done
- **T-0005** Second brain v0 - Memory entries with provenance, correction, expiry and full-text search
- **T-0006** Action contract and Hub side of the desktop agent link - pairing, token, WebSocket, heartbeat, idempotent dispatch
- **T-0007** Desktop agent core - connect out, reconnect with backoff, whitelist registry, at-most-once executor
- **T-0008** WindowsAdapter and real local verification - open a test URL and a temp folder, verify windows, prove one execution per key
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
- **T-0020** progress.md keeps a hand-written 「今天」 section and counts merge-commit PRs
- **T-0021** Model layer - ModelProvider, DeepSeek adapter, FakeProvider, ModelCall, dated prices and the monthly budget
- **T-0022** Email summaries - one AI summary per new mail, sensitive mail never sent, budget and key states
- **T-0023** AI summaries in the web UI - DeepSeek key form, monthly spend, summaries on 最近邮件 and 今日
- **T-0024** LiteLLM behind the model door - DeepSeek through litellm-core, every T-0021 guarantee kept
- **T-0025** Concise mail - AI title (what + deadline), importance, distilled points, low-value collapsed, a 邮件 page
- **T-0026** Fix mail summaries failing on real mail - DeepSeek thinking off, prompt v3, long links shortened, failed rows retried once
- **T-0027** All mail history - IMAP backfill newest first, every mail summarised once
- **T-0028** Low-value mail listed in time order, marked 次要, not collapsed
- **T-0029** Watchdog - the Hub task checks every 5 minutes that the supervisor runs

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-09 至 2026-11-15）

本周合并了 37 张任务卡：D0-01, D0-03, D0-05, D0-06, D0-07, D0-08, D0-10, D0-12, T-0001, T-0002, T-0003, T-0004, T-0005, T-0006, T-0007, T-0008, T-0009, T-0010, T-0011, T-0012, T-0013, T-0014, T-0015, T-0016, T-0017, T-0018, T-0019, T-0020, T-0021, T-0022, T-0023, T-0024, T-0025, T-0026, T-0027, T-0028, T-0029。

- 2026-11-11 feat(run): watchdog - the Hub task checks every 5 minutes that the supervisor runs (T-0029) (#39)
- 2026-11-11 feat(web,hub): list low-value mail in time order, marked 次要, not collapsed (T-0028) (#38)
- 2026-11-11 feat(hub): all mail history - IMAP backfill newest first, every mail summarised once (T-0027) (#37)
- 2026-11-11 fix(hub): mail summaries failed on real mail - DeepSeek thinking off, prompt v3 (T-0026) (#36)
- 2026-11-11 chore(claude): assistant merges every PR and updates the always-on Hub (D0-12) (#35)
- 2026-11-11 feat(hub,web): concise mail - AI title, importance, points, low-value collapsed, 邮件 page (T-0025) (#34)
- 2026-11-11 feat(hub): route model calls through LiteLLM (litellm-core), every guarantee kept (T-0024) (#33)
- 2026-11-11 feat(web,hub): AI summaries in the UI - DeepSeek key form, spend, 需要处理的邮件 (T-0023) (#32)
- 2026-11-11 Merge pull request #31 from iamflashlin/t/0022-summaries
- 2026-11-11 feat(hub): model layer - DeepSeek adapter, cost log and US$10 monthly cap (T-0021) (#29)
- 2026-11-11 docs: record the user's eight-phase roadmap and the chosen order (ADR 0026) (#30)
- 2026-11-11 feat(agent): Windows adapter - open, find and capture our own windows (T-0008) (#15)
- 2026-11-11 feat(tools): progress.md keeps a 「今天」 note and counts merge-commit PRs (T-0020) (#28)
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

## 需要注意

- `docs/tasks/D0-12.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0008.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0020.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0021.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0022.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0023.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0024.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0025.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0026.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0027.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0028.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0029.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
