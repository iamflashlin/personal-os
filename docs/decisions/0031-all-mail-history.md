# 0031 - All mail history is read and summarised once

- Status: accepted (the user, 2026-11-11: "全部邮件")
- Card: T-0027. Amends ADR 0022 (the first sync read only 14 days) and ADR 0027 (summaries
  covered only 14 days).

## Decision
- **The IMAP connector backfills history.**
  - Each sync reads new mail first, then up to 200 older messages, newest first, until
    nothing older is left.
  - The cursor keeps `backfill_below` (history below this UID is unread) and
    `backfill_done`.
  - A cursor from before this change starts below `last_uid` and so reads stored mail
    again. That mail is recognised by its external id and stored once.
  - A history message the server refuses becomes a note, so history never blocks new
    mail.
  - A changed UIDVALIDITY restarts history.
- **Summaries cover all synced mail, newest first,** so today's mail is ready while history
  fills in. New mail always runs ahead of history in every run. Mail without a receive
  time is included.
- **Scaling to thousands of mails.**
  - Runs and status use a body-free index (id, received, last change).
  - A body is loaded only for mail that is new or changed since its summary row was
    written, and for the at most 20 mails a run or status estimate needs.
  - A history message that fails is retried by later syncs and becomes a note after 3
    tries; one listed but gone is skipped. So one bad message never stalls history.
  - A mailbox with no mail in the first-sync window still reads its history; the upper
    bound comes from the server (`SEARCH ALL`). Each mail is summarised once (ADR 0027 and 0029). The monthly cap (ADR 0025)
  stops a run before any call that would exceed it. Mail then waits as pending, and
  连接/今日 say 「本月 AI 预算已用完」.

## Consequences
- With a 15-minute sync interval, history arrives at about 200 mails per sync. Each
  sync queues summary runs of 20 mails, which continue until none is due.
- Cost is about US$0.0003 per mail (measured on the user's mail with prompt v3 and
  thinking off). 10 000 mails would be about US$3, within the US$10 cap.
- Storage: stored bodies are capped (8 000 characters). On the user's mailbox the
  average is about 1.6 KB, so 10 000 mails are roughly 20-80 MB in SQLite, in
  `D:\dev\personal-os-data` (drive D; drive C is never used).
- A sync still loads the integration's stored rows to upsert. That is fine at tens of
  thousands of rows, and worth revisiting beyond that.
- The 邮件 page still lists the newest 100. Browsing history comes with search and chat
  (T-0028).
