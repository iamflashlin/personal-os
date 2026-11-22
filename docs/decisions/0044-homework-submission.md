# 0044 - 作业: the Hub owns homework submission, not grades

- Status: accepted (the user, 2026-11-22: "GPA先不用你管了…你只需要管作业提交就行";
  "先只要hub上通知")
- Card: T-0066
- Phase 7 (real execution) and Academic OS (vision direction 2).

## Context

Canvas sync already stores each assignment's submission state, submitted time, and the
missing / late / excused flags. 今日 lists missing work and deadlines, but nothing shows
what was handed in, nothing gets the user to the submission page, and nothing confirms
a submission after the user makes it.

## Decisions

1. **New module `apps/hub/homework`, no table.** The board is computed from synced Canvas
   assignments on every request: missing (Canvas's own flag), due within 24 h, due within
   7 days, submitted in the last 7 days. Excused work and combined-class copies are left
   out: `gpa.missing_copies(include_open=True)` also drops a copy that is not due yet, so
   work handed in early in one section is not asked for again; an open copy must share the
   due time too, since a title alone could hide a real deadline. Assignments with no due
   date, or due more than 120 days ago, are not listed (`items_between` selects by due
   time, the same window 今日 uses).
2. **Submitted means Canvas says so.** `submission_state` in submitted / graded /
   pending_review, as the schedule already uses. 我交了，查一下 only asks for a Canvas sync
   (`POST /homework/check`); the page waits for the sync jobs that click queued (a
   scheduled sync that finished earlier does not count), then reloads once.
3. **去提交 is a whitelisted `open_url` of the assignment's own Canvas URL**, dispatched
   through `actions.service.dispatch` with the key `homework:<Idempotency-Key>`. The Hub
   takes the URL from the synced item, never from the browser, so the page cannot make
   the agent open anything else. The window title must contain the assignment name. An
   item without a Canvas link gets 422 and no 去提交 button.
4. **Reminders stay inside the Hub.** 今日 shows the nearest unsubmitted item due within
   24 h; the sidebar shows a count. Windows notifications are a later, separate choice.
5. **The system never writes or submits work.** It tracks, reminds and opens pages.

## T-0067: 排时间

6. **A suggested time, never an automatic one.** `GET /homework/{id}/slot` returns the
   earliest free slot (the schedule's free time: inside 08:00-22:00 local, not blocked by
   any event) of at least 60 minutes that ends before the homework is due (missing work:
   within the next week; never more than 14 days ahead), starting on a quarter hour.
   Nothing is stored until 排进日程 (`POST /homework/{id}/plan`).
7. **The block is an ordinary schedule event** (kind task, 「写作业：<name>」), so 日程 shows
   it, finds conflicts with it and lets the user move or delete it. Its notes hold the
   Canvas link and a `homework:<item id>` line; the board finds the block by that line, so
   no table or migration is needed and a moved or deleted event is reflected. One block per
   homework: planning it again returns the block already there.
