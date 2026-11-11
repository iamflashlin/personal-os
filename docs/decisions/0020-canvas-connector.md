# 0020 — Canvas connector: REST API with a personal access token

- Status: accepted (decided by Claude; the user gave the school's Canvas address on
  2026-11-10. Connecting the real account needs the user's own token, created and entered
  by them, so nothing is authorised here)
- Date: 2026-11-10
- Card: T-0015. Builds on ADR 0018 (credentials) and 0019 (integrations).

## Decisions

1. **What is read.** The connector reads, read-only:
   - active courses (`GET /api/v1/courses?enrollment_state=active`);
   - each course's assignments with the user's submission
     (`include[]=submission`): due date, points, submitted, graded, missing or late, link;
   - announcements from the last 30 days up to tomorrow (`GET /api/v1/announcements`).
     `end_date` is always sent: without it, Canvas stops the window 28 days after
     `start_date`, which would drop the newest two days.

   Announcement HTML becomes plain text: block tags separate words and inline tags
   disappear. Nothing is ever written to Canvas.
2. **Settings outside the secret.** Integrations get a non-secret `config` (migration
   0009, existing rows get `{}`), checked per kind:
   - Canvas needs `base_url`. It must be https (http only on this PC, for tests), must
     not contain a user name or password (config is shown and audited), and is normalised
     to scheme and host, with a default port such as `:443` dropped so that Canvas's
     absolute page links match it;
   - a calendar feed takes no settings;
   - anything secret-looking in config is refused as an unknown setting.
3. **The token never leaves the Canvas origin.** urllib would carry the `Authorization`
   header along, even after an https→http redirect.
   - Every request, every `Link: rel="next"` page (relative links are resolved first)
     and every redirect is checked against the configured scheme, host and port.
   - Anything else is refused before the token is sent.
   - Tests prove that a server on another port receives no request at all, and that an
     https→http downgrade is refused.
4. **Errors never quote the token or URLs.**
   - 401 or 403 on the course list gives "Canvas refused the token (HTTP 401); create a
     new one in Canvas".
   - 401 or 403 on one course's assignments (a hidden tab, a concluded course) skips that
     course and syncs the rest. The cursor counts the skipped resources.
   - Reaching the page cap is an error, not a silent cut.
   - Odd JSON shapes (a list where an object belongs, an id that is not a number) skip
     that entry instead of failing the sync.
   - Other failures give a status or an exception type only.
   - There is a 120 s deadline per sync, at most 20 pages per list, and at most 10 MB
     per page.
5. **Item identities.** Assignments are `canvas_assignment` with the external id
   `<course>:<assignment>`. Announcements are `canvas_announcement` with the announcement
   id. A re-sync updates in place (ADR 0019).
6. **Web page.** The 「连接」 page gets a Canvas form with the school address and the token,
   in a masked text field as for feeds. The school address is not built into the code,
   because it is the user's personal detail and the repository is on GitHub.
   - Assignments show 缺交, 已提交 or 已评分. Canvas marks work as missing only after its
     due date, so missing work from the last 7 days is listed in 「接下来 14 天」 too.
   - Past and upcoming items are fetched in two windows, so a busy calendar cannot crowd
     out what is coming.
   - Announcements from the last 7 days get their own 「最近公告」 section.
   - Canvas syncs hourly by default.

## Known limitation

An assignment deleted or unpublished in Canvas, or one from a dropped course, stays
stored, because a sync only adds and updates (ADR 0019). The page shows missing work for
7 days only, so a stale 缺交 fades from view. Pruning items that a complete sync no longer
returns is a follow-up.

## 未验证 and the spike that settles it

The real API of the user's school Canvas (its address is kept out of the repository) has not been called, because no token
exists yet, and a school can switch off personal access tokens.

Spike (≤ 15 minutes, done by the user):
1. In Canvas: Account → Settings → "+ New Access Token".
2. Paste the token into the 「连接」 page's Canvas form.
3. Check that assignments appear.

If the button is missing, the school has disabled tokens. The calendar feed (ADR 0019)
then remains the way in.
