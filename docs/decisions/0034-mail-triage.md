# 0034: Mail triage inside Personal OS - 已处理 state, groups, batches, rules

Status: accepted (2026-11-11). The user, on the two questions asked: "这两件事按照你推荐的来":
- yes to new Hub tables for an in-app 已处理 state and saved rules;
- no write-back to the 163 mailbox for now.

## Context
The user wants AI help to get through 157 unread mails quickly: find what matters, then
clear the rest in batches. The mailbox stays read-only (ADR 0022).

## Decision
- **Three tables** (migration 0013), each with the HANDOFF §4.3 columns:
  - `mail_triage_state` holds an explicit mark per mail (handled / unhandled / none) and
    its `prev_state`, so undo can restore it. It cascades with the mail.
  - `triage_batch` is one click: what it applied, and whether it was undone.
  - `triage_rule` is a saved 「以后也这样」 with a tiny selector. Rules are switched off,
    never deleted.
- **Handled is decided at read time.** An explicit mark wins; otherwise any enabled rule
  that matches counts. A rule therefore covers new mail as soon as it is synced and
  summarised, and switching it off reverses that at once. There is no job and no worker
  hook.
- **Groups are made by code** from the summary fields, with no model call. Every open mail
  lands in exactly one group (first match wins), in this order: due within 7 days, overdue,
  grade notices, per course (the "CIS D022A" part of the Canvas code), needs action,
  low-value mail from a sender domain with 5 or more such mails, other low-value mail, not
  summarised, other.
  - Only the sender and low-value groups offer a rule; deadline groups do not.
  - On the user's real mailbox (a copy): 157 open mails in 12 groups, in 30 ms.
- **Rule language:** an AND of at most 4 conditions.
  - Text conditions are plain contains/equals, after NFKC and casefold, on sender, sender
    domain, subject or AI title. ASCII values need at least 3 characters, and control
    characters are refused.
  - Flags come from the summary fields.
  - There is no regex, OR or wildcard; ".*" matches only those two characters.
  - Domain equality also covers subdomains.
- **Safety:**
  - Every change is a person's click: a group button, one mail's toggle, undo, or a rule
    switch.
  - The server recomputes the group itself and touches only its current open mails.
  - A rule's selector is built by the server, never sent by the client.
  - Ids that belong to another owner, or are not email, are dropped.
  - Audit events hold counts and ids, never mail text.
- **Later cards:**
  - free-text commands through the model ("Handshake 的都不用看" becomes a proposal the
    user confirms);
  - leaving handled mail out of 今日's counts.

## Consequences
- 「未处理」 = unread and not handled. Mail read on the phone more than 7 days ago may
  still show as unread, because IMAP read flags are refreshed for the last 7 days only.
  This is 未验证: compare a few mails with 163 web mail (≤30 min).
- If a summary is redone and flips `low_value`, mail that a rule had handled can come back.
  This is visible, and batches are not affected.
