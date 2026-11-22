# 进度报告

<!-- today:start -->
## 今天

2026-11-22（你睡觉时做的，醒来看这里）

- **做完了**（已合并并装到 Hub 上，打开 http://127.0.0.1:8765）：
  - **「开始学习」**：「今日」和「课程」页最上面多了一张卡，写着现在该学什么、为什么（离考试最近、最没把握的那一节），以及上次学到哪。现在算出来的是：英语期末还有 11 天，先复习“S5 主题句与过渡词”。
  - 点「开始学习」→ 列出要在电脑上打开的东西 →「确认打开」后，电脑助手替你打开 Canvas 上的对应资料，每一项显示“已打开”或“没打开成功”（原因用中文说）。学完点「学完了」，自动换到下一节。
  - 电脑助手可以跟 Hub 一起常驻（开机自动启动、崩了自己重启），但**默认关着**，要你自己打开一次（见下面）。
  - 11/12 下午到 11/14 的页面简化（成绩、今日、课程、日程、邮件、连接各自先给一个答案）也都在线上。
- **等你**：
  - 决定要不要让电脑助手常驻（推荐：要）。要的话，在 PowerShell 里运行下面这一行（作用：让 Hub 配对电脑助手，并打开常驻开关），最后一行应该是“电脑助手已连上……”：
    `powershell -NoProfile -ExecutionPolicy Bypass -File D:\dev\personal-os\scripts\run\enable-agent.ps1`
    以后想关掉：同一行末尾加上 ` -Disable`。
  - 打开之后，在「今日」点「开始学习」→「确认打开」试一次，告诉我浏览器打开的页面对不对、卡片上显示的是“已打开”还是“没打开成功”。（Canvas 页面的标题能不能被认出来，我没法在你睡觉时验证，因为要用你浏览器里的 Canvas 登录。）
- **下一步**：
  - 你试过之后，根据真实的 Canvas 页面标题修正“认窗口”的规则。
  - 本地课件文件夹：给每门课设一个文件夹，「开始学习」时一起打开。
  - 「连接」页第二步、CIS 的知识地图、考后错题分析（需要你上传批改后的试卷照片）。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-22` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ e8c5fc6（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 76 张任务卡：已完成 74，进行中 0，待审核 0，卡住 0，未开始 2。

### 已完成

- **D0-01** Repository skeleton, uv + pnpm, tools.check quality gate, CI
- **D0-03** CLAUDE.md, permission rules, architect/reviewer/tester subagents, .mcp.json
- **D0-05** Spike - open Notepad, screenshot, read title via pywinauto, close
- **D0-06** ARCHITECTURE.md and ADRs for modular monolith, SQLite, agent-initiated connection
- **D0-07** tools/report.py generates docs/progress.md from task cards and git log
- **D0-08** Record the product vision, propose a realigned roadmap, and housekeeping
- **D0-10** Assistant merges safe PRs; plain-language PR summary and daily progress
- **D0-12** Assistant merges every PR; update-only script for the always-on Hub
- **D0-13** Fast lane for UI-only fixes (one review round), try pages on the live Hub first
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
- **T-0030** Ask about my mail - POST /chat/ask answers from stored summaries
- **T-0031** 邮件 page chat box - ask, see cited mails, open them
- **T-0032** install-always-on.ps1 deploys origin/main by default; the watchdog fires without a new logon
- **T-0033** 邮件 lists every mail with 全部 / 未读 / 需处理 filters
- **T-0034** 邮件 list polish - honest filter checks, chunk test, no hidden-tab polling, memoized rows
- **T-0035** Hub mail triage - in-app 已处理, code-made groups, batches with undo, rules
- **T-0036** 邮件 page - 帮我整理 panel, 未处理 filter, per-mail 已处理, undo
- **T-0037** Triage groups open their mails; mail text keeps paragraphs and short links
- **T-0038** A mail marked 已处理 no longer shows or counts as 未读
- **T-0039** Mail assistant - tool calling over all mail, full text, proposals confirmed in the UI
- **T-0040** Canvas sync for GPA - course scores and group weights, assignment groups and grades, module materials
- **T-0041** GPA management - 成绩 page per course from Canvas (score, groups, completion, missing, upcoming, grade lines, materials)
- **T-0042** The assistant makes the proposal it promises (no "点确认" without a button)
- **T-0043** Schedule - own events (weekly repeats), merged agenda with calendar and Canvas deadlines, conflicts, free time
- **T-0044** 简报 - outside information in one place, today vs history, read/unread, manual add
- **T-0045** Schedule follow-ups - overnight events, kept zone on edit, confirm deleting a weekly series, free time from now
- **T-0046** Data connection center - the six data kinds and each one's status on 连接
- **T-0047** Review leftovers - promise pattern, GPA contract comments, local-day digest dedup, test hardening, graded fake Canvas item
- **T-0048** Data kinds overview - status badges do not wrap
- **T-0049** Academic OS step 1 - course profiles from the syllabus; grade engine follows them (scale, units, own weights)
- **T-0050** Redesign - grouped sidebar, page headers, design tokens, distinct cards, dark mode
- **T-0051** Academic OS step 2 - course knowledge map, assessment links, inferred mastery, exam maps (Hub)
- **T-0052** Academic OS step 3 - 课程 page (knowledge map, mastery) and the exam center; 今日 agrees with 成绩 on missing copies
- **T-0053** Academic OS - sections link their Canvas work by title (courses without section numbers), ECON map
- **T-0054** 成绩 page - one answer first (GPA, one line per course), details behind a click
- **T-0055** Shared page header and 今日 - one sentence, then aligned rows (when, what, from)
- **T-0056** 今日 leaves out mail marked 已处理 and mail whose deadline has passed
- **T-0057** 课程 page and exam review map - aligned rows, details behind a click
- **T-0058** 日程 page - one week as a list of days, rows aligned (time, what, course)
- **T-0059** 邮件 page - one row per mail (when, what, one state word); counts on the filters
- **T-0060** 连接 page, step 1 - connected sources first, add forms on demand, no intro paragraph
- **T-0061** 开始学习 (Hub) - a study plan per course, start it on the PC, finish it, get the next one
- **T-0062** 开始学习 (web) - the next step on 今日 and 课程, confirm, see each step open, 学完了
- **T-0063** The always-on Hub keeps the desktop agent running, once the user enables it
- **T-0064** 开始学习 polish - offline sentence fits the page, agent reasons in plain Chinese
- **T-0065** 开始学习 - step reasons anchored to the agent's exact messages (T-0064 review nits)

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-16 至 2026-11-22）

本周合并了 5 张任务卡：T-0061, T-0062, T-0063, T-0064, T-0065。

- 2026-11-22 fix(web): step reasons anchored to the agent's exact messages (T-0065) (#79)
- 2026-11-22 feat(run): the always-on supervisor keeps the desktop agent running, once enabled (T-0063) (#77)
- 2026-11-22 fix(web): 开始学习 offline sentence fits the page, agent reasons in plain Chinese (T-0064) (#78)
- 2026-11-22 feat(web): 开始学习 - next step on 今日 and 课程, confirm, see each step open, 学完了 (T-0062) (#76)
- 2026-11-22 feat(hub): 开始学习 - study plan per course, start it on the PC, finish, next (T-0061) (#75)

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
- `docs/tasks/D0-13.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
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
- `docs/tasks/T-0030.md`：已经合并进 main，但第 4 行还写着 status: in_progress（打开这个文件，改成 status: done）
- `docs/tasks/T-0031.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0032.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0033.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0034.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0035.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0036.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0037.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0038.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0039.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0040.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0041.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0042.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0043.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0044.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0045.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0046.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0047.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0048.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0049.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0050.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0051.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0052.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0053.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0054.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0055.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0056.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0057.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0058.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0059.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0060.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0061.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0062.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0063.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0064.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0065.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
