# 0012 — Realign the roadmap to the user's vision (PROPOSAL)

- Status: **proposed — waiting for the user's decisions below. Nothing here is adopted.**
- Date: 2026-11-10
- Inputs: `docs/VISION.md` (the user's eight directions), `docs/HANDOFF.md` §3, §8

## Context

On 2026-11-10 the user said that HANDOFF.md's vision and feature set may drift from what
they want, and that feature design should follow their own eight directions
(`docs/VISION.md`). HANDOFF stays the source for engineering rules.

This ADR compares the two. It proposes a roadmap change and lists the decisions only the
user can make. It changes no code and does not touch HANDOFF.md.

## What is already built (and stays useful under either plan)

Hub with SQLite/Alembic, the goal/project/task/workspace model, the redacted audit log,
idempotency, export/import, Evidence with user confirmation, and a desktop web page.
These are the base for directions 1, 2, 3 and 8. Nothing needs to be rebuilt.

## Gap analysis: each direction against the current plan

| # | Direction (VISION.md) | Current plan (HANDOFF §8) | Gap |
|---|---|---|---|
| 1 | 个人第二大脑 | Memory "简版" in S7, late | Underweighted. In the vision it is the foundation the other directions read and write |
| 2 | 主动规划与人生管理 | Task CRUD only; no daily plan, no "back to the main line" | Missing |
| 3 | 数字世界的执行者 | V0.1 opens URLs and folders; GUI operation is P1 | Deliberately deferred (highest technical risk); the vision calls it one of the most important, so it needs a dated place on the roadmap |
| 4 | 个人能力增强器 | S6: Human-led C++ tutoring | Narrow: research, writing and analysis are absent |
| 5 | 手机、电脑、耳机统一联动 | iOS Shortcut dictation → one POST | Large gap: no continuous voice conversation while commuting |
| 6 | 感知环境与主动服务 | HANDOFF §3 item 10: time, calendar and device status only; **no location** | Deliberate privacy cut that conflicts with the vision (location, email follow-up, body state) |
| 7 | 个人生活与自律系统 | Absent (no sleep, gaming, fitness or finance) | Missing |
| 8 | 成长反馈与自我优化 | "每日看板" in S7 | Mostly missing: skill growth, achievements, weekly report, workflow optimisation |
| — | Target experience: morning brief | Calendar "之后"; Canvas P1 (unverified); email not planned | The first scene the user describes is not in V0.1 |
| — | Dev factory separate from product | HANDOFF §3 item 1 agrees | Aligned |
| — | Smart home excluded | Excluded | Aligned |

## Proposal (default recommendation, pending the user's decisions)

1. **V0.1 becomes "one connected day".** Each direction gets its smallest useful piece,
   so the whole chain (记忆 → 规划 → 启动 → 执行 → 成长) works end to end once:
   - **Morning:** today's brief from tasks, due dates and the calendar (2).
   - **"开始学习":** the PC prepares the environment and shows the last next step (1, 3).
   - **Studying:** Human-led help (4).
   - **Commute:** talk to it from the phone; ideas become tasks or notes (minimal 5).
   - **Evening:** what got done with evidence, and tomorrow's first step (minimal 8).
2. **Memory moves to the second slice**, right after the existing Hub core, because every
   other direction reads and writes it.
3. **Planned later with a stated slot, instead of unmentioned:**
   - full GUI execution on arbitrary apps (3, after the S2 desktop agent is proven);
   - location and body-state sensing (6);
   - the life domains (7).
4. **Engineering rules are unchanged:** evidence before done, reviewer, owner_id, audit,
   export, and Human-led for coursework.

## Decisions only the user can make

1. **Adopt the proposal?** If yes, Claude rewrites HANDOFF §8 (the roadmap) in a PR and
   then cuts task cards in the new order.
2. **Privacy boundary for direction 6.** Is location, email content or body-state data
   (sleep, exercise) collected in V0.1?
   - Default recommendation: no location and no body data yet; email headers only
     (sender and subject).
3. **Earbud voice conversation (direction 5).** Is it in V0.1, or is it replaced at first
   by phone typing and voice input?
   - Real-time voice needs a paid model API and is the most expensive and uncertain
     piece (未验证).
4. **Which life domain first (direction 7).** Sleep, gaming time, fitness or finance?
5. **Morning brief sources (target experience).**
   - Calendar: which one?
   - Canvas: does the school allow personal access tokens? (未验证)
   - Email: which account?
   - Each source may need an account authorisation, which the user must approve.

## Consequences

- Until the user decides, work continues only on items that fit both plans: merging the
  open PRs and housekeeping. No new product slice starts.
- After the decisions, HANDOFF §8 is rewritten and this ADR becomes `accepted` (or
  `rejected`), with the user's answers recorded here.
