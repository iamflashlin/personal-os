# 0023 — 今日 view: one day across tasks and synced sources, computed on request

- Status: accepted (it shows only data the user already chose to sync; ADR 0012 put
  Canvas and email first in the brief)
- Date: 2026-11-11
- Card: T-0019. Builds on ADR 0019 (integrations), 0020 (Canvas) and 0022 (email).

## Decisions

1. **A new read-only Hub module, `apps/hub/briefing`.** It owns no table and writes
   nothing. It reads tasks and synced items only through `tasks.service` and
   `integrations.service` (new: `items_between`, filtered by owner through the
   integration). `GET /today` returns a `TodayView` contract.
2. **Computed on request, not stored.** The view is cheap at personal scale (a few hundred
   items over an 18-day window), and always reflects the last sync. Nothing needs to be
   regenerated or cleaned up.
3. **"Today" is the user's day.** The browser sends its IANA zone (`?tz=`), because the
   user's day is where they are, not where the Hub runs. An unknown zone is a 422. With
   no zone, this PC's current offset is used. All-day items are stored at UTC midnight of
   their day, so their day is read in UTC, never shifted.
4. **What goes where.**
   - Due today: Canvas assignments and open tasks due on the local date.
   - Next 3 days: assignments, tasks and events after today.
   - Missing/overdue: assignments Canvas marks missing (due in the last 120 days, a
     whole term, read in a second query limited to assignments) and open tasks past their
     due date.
   - Events: calendar items starting today.
   - Unread mail: from the last 24 hours, newest first, at most 8 shown, all counted.
   - Announcements: from the last 48 hours.
   - In progress: tasks in progress.
   - Problems: sources whose last sync failed, with their error.
   - The headline is a plain sentence counting these. No model writes it yet. When a
     source failed, it starts by saying so, so stale data never reads as an all-clear.
   - Within a day, all-day items come first, then by time. The cross-source query is not
     capped: it is bounded by time, and a silent cut would drop real deadlines.
5. **Web.** 「今日」 is the first tab and the page that opens. It refreshes every 5
   minutes, links only http(s) URLs, and when nothing is connected says so with a button
   to 「连接」. If the Hub does not know the browser's zone name (422), the page asks again
   without one and uses the PC's zone.

## Not covered yet

- An event that started before today and runs into it is not listed under today.
- Pop-up cards at set times and model-written summaries wait for the user's routine.
