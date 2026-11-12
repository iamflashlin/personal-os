# 0039: The 简报 - outside information, today vs history, read/unread

Status: accepted (2026-11-12). The user wants three things in one briefing, with sources
connected later:
- important current events (they invest);
- club events posted on IG and Discord;
- useful tips distilled from a WeChat transfer group that is mostly chit-chat.

It separates today from history and tracks read/unread.

## Decision
- **Table `digest_item`** (migration 0015, HANDOFF §4.3 columns). Each row holds a
  channel (news | club | group | other), the source name, title, summary (the distilled
  points), the raw text (the original, kept as is), the link, topics, the publish time, an
  event time, an important flag and the read time.
- **Dedup** is unique per owner: by channel, source and link; without a link, by title
  and publish day, so a weekly post under the same title comes back as a new item. A future
  publish time is clamped to now.
- **Views.** `GET /digest?view=today|history`. Today starts at local midnight. Within
  today, unread and important items come first; history is newest first, capped at 300.
  Unread counts are given for both views and per channel.
- **Writes.** Add an item, mark one read or unread, or mark what is on screen read (the
  view, and the chosen channel if any). All are
  audited. Opening an item in the web marks it read.
- **No sources and no model yet.** Items come in by hand now. Connectors (news feeds, IG,
  Discord, a WeChat export) will write through the same `add`, with `source` set to their
  name. Distilling a WeChat chat with DeepSeek would send other people's messages to an
  outside AI, which goes beyond what the user has agreed to so far. It waits for their
  decision ("不默认把私人原始数据发送到外部 AI").
