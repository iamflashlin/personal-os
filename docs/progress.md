# 进度报告

<!-- today:start -->
## 今天

2026-11-12（通宵做的，早上看这里）

- **做完了**（都已合并并装到你电脑上的 Hub，打开 http://127.0.0.1:8765 就能用）：
  - **邮件助手**：在“邮件”页顶部直接提问，比如“哪些邮件还没处理”。它会自己搜邮件、读邮件；要把邮件标为“已处理”时，会先给你一个方案，你点确认才会执行。
  - **成绩**：新增“成绩”页，从 Canvas 读你 4 门课的分数、权重和缺交作业，估算 GPA，并算出想拿 A 还需要多少分。现在估算 GPA 3.92；英语 A-，有 2 份缺交。
  - **日程**：新增“日程”页，按周显示你自己加的课和活动、日历订阅和 Canvas 截止，会提示时间冲突和空闲时段。每周重复的课程删除前会先问你。现在只是功能，没有替你排任何事。
  - **简报**：新增“简报”页，分“今天”和“历史”两栏，有已读/未读。用来放时事、社团活动和微信群精华；来源还没接，现在可以手动添加。
  - **数据连接中心**：“连接”页最上面按 6 类数据显示状态：学业和邮件都是“正常”，带着最近同步时间。出错时会写原因，太久没同步会标“可能过期”。
  - 今天合并了 #50 到 #59，每一个都在 Windows 和 Ubuntu 两个系统的检查通过后才合并。
- **等你拍板**（都不急，想好了告诉我就行）：
  - **微信群精华要不要用 AI 提炼？** 推荐：先不用。群里是别人的发言，发给 DeepSeek 超出了你之前的同意范围。不用 AI 的话，我可以只按关键词（转学、选课、截止等）在本地筛选。
  - **每门课几个学分？** 告诉我 4 门课的学分，GPA 就能按学分加权，现在是平均算的。
  - **课程大纲里的分数线**（比如 93 分以上算 A）：如果和默认的不一样，把大纲发我，我按大纲算。
  - **文件放哪里？** 推荐：Google Drive。你以后要接 Gmail 和 Google 日历，放在同一个账号里最省事；WPS 本地文件也能接，只是要多做一套读取。
  - Gmail 接好以后，要不要删掉 Hub 里保存的 163 邮件数据？到时候我再问你。
  - 有个临时文件夹 `D:\dev-cache\t0032-copy` 我删不掉（没有权限），你可以自己删：在资源管理器里打开 `D:\dev-cache`，删掉 `t0032-copy` 文件夹。
- **下一步**：
  - 按路线图做第 3 阶段：Canvas 作业变动提醒和 Google 日历（Google 日历要你登录授权，到时会先问你）。
  - 小修：“连接”页里有个标签会折成两行。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-12` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ bf992b5（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 58 张任务卡：已完成 56，进行中 0，待审核 0，卡住 0，未开始 2。

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

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-09 至 2026-11-15）

本周合并了 56 张任务卡：D0-01, D0-03, D0-05, D0-06, D0-07, D0-08, D0-10, D0-12, D0-13, T-0001, T-0002, T-0003, T-0004, T-0005, T-0006, T-0007, T-0008, T-0009, T-0010, T-0011, T-0012, T-0013, T-0014, T-0015, T-0016, T-0017, T-0018, T-0019, T-0020, T-0021, T-0022, T-0023, T-0024, T-0025, T-0026, T-0027, T-0028, T-0029, T-0030, T-0031, T-0032, T-0033, T-0034, T-0035, T-0036, T-0037, T-0038, T-0039, T-0040, T-0041, T-0042, T-0043, T-0044, T-0045, T-0046, T-0047。

- 2026-11-12 feat(web): data connection center - six data kinds and their status (T-0046) (#58)
- 2026-11-12 fix(hub,web): review leftovers - promise pattern, GPA comments, local-day digest dedup, tests (T-0047) (#59)
- 2026-11-12 fix(hub,web): schedule follow-ups - overnight events, kept zone, confirm series delete, free time from now (T-0045) (#57)
- 2026-11-12 feat(hub,web): 简报 - outside information, today vs history, read/unread (T-0044) (#56)
- 2026-11-12 feat(hub,web): schedule - own events, agenda with calendar and Canvas, conflicts, free time (T-0043) (#55)
- 2026-11-11 feat(hub,web): GPA management - 成绩 page per course from Canvas (T-0041) (#54)
- 2026-11-11 feat(hub): Canvas sync for GPA - course scores and weights, assignment groups and grades, module materials (T-0040) (#53)
- 2026-11-11 fix(hub): the assistant makes the proposal it promises (T-0042) (#52)
- 2026-11-11 feat(hub,web): mail assistant - tool calling over all mail, full text, proposals confirmed in the UI (T-0039) (#51)
- 2026-11-11 fix(web): a mail marked 已处理 no longer shows or counts as 未读 (T-0038) (#50)
- 2026-11-11 chore(claude): fast lane for UI-only fixes - one review round, try pages live first (D0-13) (#49)
- 2026-11-11 fix(web,hub): triage groups open their mails; mail text keeps paragraphs and short links (T-0037) (#48)
- 2026-11-11 feat(web): 帮我整理 panel on 邮件 - groups, one-click 已处理, undo, rules, 未处理 filter (T-0036) (#47)
- 2026-11-11 feat(hub): mail triage - in-app 已处理, code-made groups, batches with undo, rules (T-0035) (#46)
- 2026-11-11 fix(web): 邮件 list polish - honest filter checks, chunk test, no hidden-tab polling, memoized rows (T-0034) (#45)
- 2026-11-11 feat(web): 邮件 lists every mail with 全部 / 未读 / 需处理 filters (T-0033) (#44)
- 2026-11-11 feat(web): chat box on 邮件 - ask, see cited mails, open them (T-0031) (#43)
- 2026-11-11 feat(hub): ask about my mail - POST /chat/ask answers from stored summaries (T-0030) (#40)
- 2026-11-11 fix(run): watchdog fires without a new logon; installer deploys origin/main by default (T-0032) (#42)
- 2026-11-11 docs: progress for 2026-11-11 (#41)
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
