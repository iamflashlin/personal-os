# 0022 — Email connector: read-only IMAP for 163 now and Gmail later

- Status: accepted (the user chose to collect email content in ADR 0012 and named a 163
  mailbox on 2026-11-10; connecting it is the user's step, so nothing is authorised here)
- Date: 2026-11-11
- Card: T-0018. Builds on ADR 0018 (credentials), 0019 (integrations) and T-0017.

## Decisions

1. **IMAP, standard library only (`imaplib`, `email`).** One connector covers NetEase 163,
   Gmail (with an app password), QQ and other password-style IMAP servers. Outlook.com
   and Microsoft 365 accept only OAuth now, so they are not offered (a later card).
   There is no new dependency.
2. **Read-only, always.** The mailbox is opened with EXAMINE, and messages are fetched
   with `BODY.PEEK[]` (or `BODY.PEEK[HEADER]` plus the first 64 KB of the text for a
   message over 5 MB), so nothing is marked as read. No STORE, EXPUNGE, COPY, MOVE or
   APPEND is ever sent. Tests check the exact command log.
3. **163 specifics.**
   - 163 refuses third-party clients the login password. The user turns on IMAP in the
     web mail settings and creates a client authorisation code (授权码), which is the
     credential.
   - NetEase answers "Unsafe Login" to SELECT/EXAMINE unless the client first identifies
     itself with the IMAP `ID` command (RFC 2971). The connector sends it after logging
     in; servers without ID simply refuse it.
4. **What is stored.** Each message becomes an `email_message` item:
   - the subject as the title; the time is the server's receive time (INTERNALDATE),
     because the Date header is set by the sender and is often missing or wrong; the
     header is kept as `sent_at`;
   - the text body, plain preferred, HTML reduced to text, up to 8,000 characters;
   - the sender's name and address, the recipients, the read state, attachment names
     (not their contents) and the Message-ID.
   - The external id is `mid:<Message-ID>|<receive time>`, or `uid:<uidvalidity>:<uid>`
     when there is no Message-ID, so a renumbered folder does not duplicate mail. The
     sender chooses the Message-ID, so it is paired with the server's receive time: a
     second mail reusing it is stored separately and never overwrites the first.
   - A message too large to read whole keeps its beginning and a note saying so. A
     message that cannot be parsed at all is stored as 「（无法解析的邮件）」 rather than
     stopping the mailbox. Charsets labelled gb2312 are read as gb18030 (Chinese mail
     often labels GBK text gb2312), unknown charsets are replaced, never fatal.
5. **Incremental.**
   - The first sync reads the last 14 days. Later syncs read only UIDs above the stored
     `last_uid`, oldest first, at most 200 per sync, within a 180 s deadline, so a
     backlog arrives over several syncs and nothing is skipped.
   - If one message is refused or the connection drops, the sync keeps what it read and
     the cursor stops at the last stored UID; the rest is retried next time. A message
     that fails on 3 syncs in a row is stored as a 「（无法解析的邮件）」 note and reading
     moves past it, so one bad message never blocks later mail for good. A message whose
     size the server does not report is read partially, like a large one.
   - Read state changes without a message changing, so for mail received in the last 7
     days (up to 300) each sync fetches FLAGS and sends `seen` updates as patches
     (`Batch.patches`), which update stored items in place. Entries age out after 7 days,
     and messages the server no longer has are dropped. Patched fields stay out of the
     content hash.
   - If the folder's UIDVALIDITY changes (the server renumbered it), reading starts again
     from the window; Message-ID ids keep this from duplicating anything.
   - Batches are never complete, so email is never pruned (ADR 0019 §2). Mail deleted
     from the server stays in the Hub.
6. **Settings (config, not secret).** These are the server, the port (993 by default),
   the address, the folder (INBOX by default) and `tls`.
   - TLS uses the system's certificate checks. `tls=off` is accepted only for a server
     on this PC, as in tests.
   - The address is personal, so it is entered by the user and never built into the code.
7. **Errors.** A refused login says "for 163 use the 授权码, not the password", and never
   quotes what was sent. A dropped connection during login is reported as a connection
   problem, not a wrong code. A code containing line breaks or non-ASCII characters is
   refused before anything is sent. Other failures name only the exception type.
8. **Web page.** The 「连接」 page gets a 「连接邮箱」 form with presets (163, Gmail, QQ),
   the address and a masked 授权码 field. A 「最近邮件（最新 30 封）」 section shows the
   newest 30 messages per mailbox (`order=desc&item_type=email_message`), with unread mail marked.
   Deleting the connection says it removes only this system's copy and the 授权码, never
   mail in the mailbox. Mail syncs every 15 minutes by default.

## 未验证 and the spike that settles it

The real 163 server has not been contacted, because no 授权码 exists yet.

Spike (≤ 15 minutes, done by the user):
1. In 163 web mail: 设置 → POP3/SMTP/IMAP → turn on the IMAP/SMTP service (phone check).
2. Copy the 授权码.
3. Paste it into the 「连接邮箱」 form with the address, then check that 最近邮件 fills.

If 163 still refuses with "Unsafe Login", the `ID` handling needs a look; the error message
says so.
