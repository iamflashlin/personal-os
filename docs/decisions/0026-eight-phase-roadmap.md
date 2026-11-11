# 0026 - The user's eight-phase roadmap

- Status: accepted (the user, 2026-11-11)
- Builds on: ADR 0012 (vision realignment) and its "one connected day" decision. Where the
  two disagree on order, this ADR wins.

## Context

On 2026-11-11 the user set out the order in which Personal OS should grow. In their words:
先搭基础 → 接入真实数据 → 实现基础功能 → 引入 AI → 实现实际执行 → 优化成本与体验. In
one sentence: "先让系统可靠地了解你，再让 AI 替你思考，最后让 AI 真正替你执行".

## Decision

### The phases

| # | Phase | Scope (the user's) | State on 2026-11-11 |
|---|---|---|---|
| 1 | AI dev toolchain | Claude Code, multi-agent collaboration, Git, automated tests | Built: quality gate, CI on two OSes, reviewer/architect/tester subagents, merge rule (ADR 0024) |
| 2 | Infrastructure | Database, API, identity and permissions, logs, backup, cross-device link | Mostly built: Hub and SQLite, audit, backup/export, credentials (ADR 0018), desktop-agent link, always-on Hub (ADR 0021). Open: permissions and authentication hardening, needed before remote access (HANDOFF S8) |
| 3 | Real personal data | First Canvas, calendar, tasks, computer usage; then email, files, location, health | Canvas connector (ADR 0020), connected to the user's real account (see note 1), ICS calendars (ADR 0019), read-only IMAP (ADR 0022, account not yet connected). Missing: computer usage, files, location, health |
| 4 | Unified data and memory | One personal data model, sync, dedup, provenance, search, long-term storage; every AI uses the same memory | Partly built: synced items with source and dedup, memory with provenance and search (T-0005) |
| 5 | Non-AI basic features | Tasks, schedule, goals, study log, progress board, notifications, simple rule automation | Partly built: tasks, 今日 page (ADR 0023) |
| 6 | AI brain | Natural language, memory retrieval, planning, context analysis, multi-model API routing and cost control | In review: model layer with cost log and monthly cap (T-0021, ADR 0025, open PR #29) |
| 7 | Real execution | Computer and browser control, multi-agent work, phone commands the PC, voice commute assistant | Prototype: Hub link and agent core merged (T-0006, T-0007); Windows adapter T-0008 waiting in PR #15 |
| 8 | Optimisation and rollout | Verified outcomes, gamified feedback, cost, security, stability, user tests, cross-platform clients | Not started |

Note 1: the user connected their Canvas account themselves after T-0015 merged.
ADR 0020 and `.evidence/T-0015` predate that. On 2026-11-11 the always-on Hub's
`GET /integrations` returned the Canvas integration with sync status `ok` (last sync
17:28 UTC), and `GET /credentials` listed its token entry (secret not shown).

### The user's three principles

1. Multi-agent dev tooling is used from the start, as the means of building everything else.
2. Data and memory come before complex AI, but nothing waits for all data. As soon as one
   source works, ship a usable feature on it (for example, Canvas → an assignment board).
3. Computer control may get early standalone prototypes, so platform limits surface
   early. Full execution still belongs to phase 7.

Technical spikes for the three capabilities (know, think, act) may run in parallel. Full
features are integrated in dependency order.

### Order chosen now (the user: "采用，但先把邮件总结做完")

1. Finish the AI email summary already under way: T-0021 (model layer, open PR #29), then
   T-0022 (summaries) and T-0023 (UI).
2. Return to phase 3, starting with the user's acceptance loop: when Canvas adds an
   assignment or changes a due date, Personal OS syncs it, dedups it, keeps its source
   and shows it correctly. The one gap is the due-date change. The new value replaces the
   old one silently, so the next card keeps the previous value and shows that the
   deadline moved.
3. Then Google Calendar (probably through the existing ICS connector; 未验证), and
   computer-usage data once the user decides what may be recorded.

## Consequences

- Each new task card names its phase (1-8) and what it depends on.
- ADR 0012's slices stay valid as content. This ADR decides their order.
- CLAUDE.md still says ADR 0012 "awaits the user". That line is out of date, and the next
  PR that touches CLAUDE.md (which the user merges) points it to ADR 0012 + 0026.
