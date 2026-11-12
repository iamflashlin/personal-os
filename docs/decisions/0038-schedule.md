# 0038: The schedule - own events plus calendar and Canvas, one agenda

Status: accepted (2026-11-12). The user wants a calendar-like schedule for classes,
activities, workouts and task blocks. Later an AI will place tasks from mail and Canvas
into free time. For now: "你只要做出这个功能就行了，暂时还不用给我排事情".

## Decision
- **Table `schedule_event`** (migration 0014, HANDOFF §4.3 columns): title, kind (class |
  activity | workout | task | exam | other), start and end in UTC, all-day, location,
  notes. Weekly repeats are days plus an optional end date, and the time zone the event
  was entered in, so a repeat keeps its local wall-clock time across daylight saving.
  Source is `manual`; an AI planner will write `ai` events the same way later.
- **Agenda** (`GET /schedule?start&end&time_zone`, at most 62 days) merges three sources:
  - the user's events, with repeats expanded;
  - synced calendar feed events;
  - Canvas assignments that are not handed in, shown as deadlines. A deadline is a point
    in time: it neither blocks time nor clashes.
- **Conflicts**: blocking entries that overlap are both marked.
- **Free time**: gaps of at least 30 minutes between 08:00 and 22:00 local, per day. This
  is the input a planner needs.
- **Writes** go through `audit.audited`; updates carry `version` (optimistic lock). Delete
  removes only the user's own event.
- **Web**: a 日程 tab with the week in day cards, conflicts and free time, a form to add
  a (weekly) event, and delete.

## Consequences
- Dedup across sources (one exam in Canvas, the calendar and mail) is not done yet: the
  same exam may show twice. That comes with cross-source linking (data-intake guidance).
- Free time ignores sleep and meals beyond the 08–22 window; the planner card will add
  user preferences.
