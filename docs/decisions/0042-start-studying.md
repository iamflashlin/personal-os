# 0042 - 开始学习: a study plan per course, run on the PC

- Status: accepted (the user, 2026-11-22: "你不用到我的地方就直接开始做吧"; the 7-hour
  plan put the execution loop first)
- Cards: T-0061 (Hub), T-0062 (web), T-0063 (agent with the always-on Hub)
- Phase 7 (real execution). Vision direction 3, and 「一键启动与专注」 in the user's
  14-system list (2026-11-22).

## Context

The user's oldest pain point is the cost of starting: before studying they must decide
what to study, find the material and open it. The Hub already knows the course map,
each section's inferred mastery and the exam review order (ADR 0041). The desktop agent
already opens URLs and verifies the window (ADR 0014-0016). Nothing joined the two.

## Decisions

1. **New module `apps/hub/study`, one table `study_session` (migration 0018).** A row
   stores what the session was for (`next`), the label and action run id of each step,
   its Idempotency-Key, and when the user finished it. Step status is never copied: it
   is read from the action run, so it is always what the agent reported.
2. **What to study next is computed, not generated.** No model call:
   - the nearest exam that is still ahead → its review map's `suggested` order (weakest
     first, ADR 0041), then the rest of its scope in teaching order;
   - no exam ahead → the weakest section (needs review, not tested, seen, practicing);
   - a section finished in the last 3 days is skipped, so 学完了 moves on.
   `GET /study/next` picks the course with the nearest exam.
3. **Steps are whitelisted `open_url` actions only**, dispatched through
   `actions.service.dispatch` (moved out of `actions/api.py` so both callers share the
   at-most-once logic). Each step's key is `study:<session key>:<n>`, and a step's state
   is read from the action run with that key, so a start cut short never hides a step
   that was sent. Replaying the session key returns the stored session (also while the
   agent is offline); if the session is still `started` and the agent is online, the
   steps that were never sent are sent then, each still at most once. The section's own
   teacher link, the course notes and the exam review sheet are opened. Each one expects
   a window title containing the item's name without its file extension.
4. **No agent, no session.** Start returns 503 「电脑助手没有连上」 and stores nothing, so
   the same key works once the agent is back.
5. **Finishing is the user's click** (`POST /study/sessions/{id}/finish` with the version
   read). Nothing is marked done from model output.

## 未验证

- Real Canvas window titles. Steps expect the Canvas item's name, for example
  "Math1A-Sec3.4" or "Math 1A - Lecture Note Packet". Whether the browser tab title for
  a Canvas module item contains that name has not been checked, because it needs the
  user's own Canvas sign-in in their browser. If it does not, the step reports `failed`
  even though the page opened. Spike (≤ 30 min, once the agent runs with the live Hub,
  T-0063): start 开始学习 for MATH and read each step's message and window evidence.
- `scripts/verify/study.py` proves the whole chain on this PC with a page served
  locally.
