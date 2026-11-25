# 进度报告

<!-- today:start -->
## 今天

2026-11-25（补上 11/22–11/25 做完的事）

- **做完了**（都已合并并装到 Hub 上，打开 http://127.0.0.1:8765）：
  - **电脑助手已常驻**：你同意后打开了。「开始学习」和「去提交」都在真机上用 Edge 打开过真实的 Canvas 页面，窗口也认出来了。
  - **「作业」页**（左边「学业 → 作业」）：缺交、24 小时内要交、这周要交、最近交了（迟交标红）。「去提交」让电脑助手打开作业的 Canvas 页面；「我交了，查一下」让 Hub 马上去 Canvas 同步，只有 Canvas 记下了提交时间才算交了。
  - **「排时间」**：没交的作业点「排时间」，Hub 在截止前找你最早的一小时空闲，点「排进日程」就进了「日程」页。
  - **「先做这个」**：「今日」最上面只给一件事和一个按钮（24 小时内要交的 → 缺交的 → 这周还没排时间的）。
  - **「这几周交作业情况」**：「作业」页最上面写这周按时、迟交、缺交、还没交各几份，下面是最近 4 周的小柱子，柱子下面也写着数字。
  - **「今天的安排」**：「今日」里把今天的课、排好的写作业时间和空闲时间按时间排成一列，标出"现在"和"下一项"。
  - **学完会进记忆**：在「开始学习」点「学完了」，「记忆」页会自动多一条"哪天学完了哪一节"，你可以改或删。
  - 按你的要求，GPA 不再管，学业只管作业提交；提醒只在 Hub 上显示。GitHub 免费检查额度用完后，你同意把仓库改成公开。
- **等你**：无。想试的话，看看「作业」页的数字和 Canvas 对不对得上。
- **下一步**：
  - 「今日」第一行的统计也算上「日程」里的事，和「今天的安排」对得上（T-0073）。
  - 每天早上主动告诉你今天先做什么（只在 Hub 上）。
  - 学期目标 → 每周目标 → 每日任务（需要你先定目标）。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-25` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ 617a447（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 84 张任务卡：已完成 81，进行中 0，待审核 0，卡住 0，未开始 3。

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
- **T-0066** 作业 - every homework's submission state, one click to its Canvas page, Hub reminders
- **T-0067** 排时间 - put an unsubmitted homework into the next free slot before it is due
- **T-0068** 先做这个 - 今日 opens with the one homework thing to do now, with its button
- **T-0069** 这几周交作业情况 - on time, late, missing and open per week on 作业
- **T-0070** T-0069 review nits - the routed weekly fake follows today; bar markup indented
- **T-0071** 今天的安排 - 今日 lists today's classes, homework blocks, deadlines and free time, marking now and next
- **T-0072** 学完了 is remembered - a finished study session becomes a memory

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules
- **T-0073** 今日 headline counts today's agenda, so it agrees with 今天的安排

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-23 至 2026-11-29）

本周合并了 2 张任务卡：T-0071, T-0072。

- 2026-11-25 feat(study): 学完了 is remembered - a finished study session becomes a memory (T-0072) (#87)
- 2026-11-25 feat(web): 今天的安排 - today's classes, homework blocks, deadlines, free time (T-0071) (#86)

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
- `docs/tasks/T-0066.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0067.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0068.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0069.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0070.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0071.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0072.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
