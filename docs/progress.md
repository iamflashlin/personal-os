# 进度报告

<!-- today:start -->
## 今天

2026-11-12（上午你睡觉时做的，醒来看这里）

- **做完了**（都已合并并装到 Hub 上，打开 http://127.0.0.1:8765）：
  - **整套页面重新设计**：左边是分组导航（今天 / 学业 / 信息 / 系统），每页顶部有标题和一句说明；颜色只用来表示状态；卡片分层次；会跟随系统切换深色模式。手机上，导航变成顶部可以横滑的一条。
  - **成绩按课程大纲计算**（Academic OS 第 1 步）：我把 4 门课的大纲都读了一遍，每门课有一张“规则卡”，写着学分、分数线、权重，以及“不收迟交”“缺考用期末顶替”“作品集审核”这类规则，每条都附上大纲原文。GPA 按学分和加减号算。和 Canvas 不一致的地方直接写出来，比如 CIS 在 Canvas 里没设权重，英语有合班课的重复作业。
  - **课程知识地图**（第 2、3 步，先做 MATH 1A）：新增“课程”页，按章列出每一节，带讲义页码、老师给这一节的资料、对应的小测和得分，以及掌握状态（根据什么判断的会写清楚，你也可以自己改）。每场考试有复习地图：先复习什么、为什么、范围外要补的前置知识、考前检查清单（附老师原文），以及复习题和答案的链接。
  - “今日”页不再把英语那两份重复作业算成缺交。
  - 学分是我自己在网上查的：MATH 1A 5 学分（De Anza 2026 年的 MATH 1A 大纲），英语 5 学分（De Anza 老师的课程页，官方目录没核实），ECON 4 学分、CIS 4.5 学分（你的大纲里写的）。
- **等你**：
  - 打开“成绩”，每门课点开“规则卡”对照一下；没问题就点“我对照过大纲，没问题”。每张卡里“待确认”的几条（比如英语的 A 线大纲没写），有机会问一下老师。
  - 打开“课程” → MATH 1A，看看知识地图对不对；有不对的地方告诉我。
  - 说明一下：你让我读的课程资料，是由我（Claude，一个云端 AI）读的，所以内容经过了 Anthropic 的服务器。Hub 本身不调用任何 AI，也没有发给 DeepSeek。
- **下一步**：
  - 给 ECON、CIS、英语也做知识地图（ECON 期中二在 11/16，先做 ECON）。
  - 考后错题分析：需要你上传批改后的试卷照片，系统才知道是哪一题、为什么丢分，不会自己编原因。
  - 跨课程“今天先学什么”的建议。
<!-- today:end -->

> 由 `uv run python -m tools.report --today 2026-11-12` 生成，「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ 6aa7b24（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 63 张任务卡：已完成 61，进行中 0，待审核 0，卡住 0，未开始 2。

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

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-09 至 2026-11-15）

本周合并了 61 张任务卡：D0-01, D0-03, D0-05, D0-06, D0-07, D0-08, D0-10, D0-12, D0-13, T-0001, T-0002, T-0003, T-0004, T-0005, T-0006, T-0007, T-0008, T-0009, T-0010, T-0011, T-0012, T-0013, T-0014, T-0015, T-0016, T-0017, T-0018, T-0019, T-0020, T-0021, T-0022, T-0023, T-0024, T-0025, T-0026, T-0027, T-0028, T-0029, T-0030, T-0031, T-0032, T-0033, T-0034, T-0035, T-0036, T-0037, T-0038, T-0039, T-0040, T-0041, T-0042, T-0043, T-0044, T-0045, T-0046, T-0047, T-0048, T-0049, T-0050, T-0051, T-0052。

- 2026-11-12 feat(web,hub): 课程 page - knowledge map, mastery, exam center (T-0052) (#65)
- 2026-11-12 feat(hub): Academic OS step 2 - course knowledge map, mastery, exam maps (T-0051) (#64)
- 2026-11-12 feat(web): redesign - grouped sidebar, page headers, design tokens (T-0050) (#63)
- 2026-11-12 feat(hub,web): Academic OS step 1 - course profiles from the syllabus (T-0049) (#62)
- 2026-11-12 fix(web): data kinds status badges stay on one line (T-0048) (#61)
- 2026-11-12 docs: progress 2026-11-12 - night summary (#60)
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
- `docs/tasks/T-0048.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0049.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0050.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0051.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
- `docs/tasks/T-0052.md`：已经合并进 main，但第 4 行还写着 status: review（打开这个文件，改成 status: done）
