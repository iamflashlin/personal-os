# 0029 - Concise mail: AI titles, importance, distilled points, low-value collapsed

- Status: accepted (the user's answers, 2026-11-11)
- Card: T-0025. Amends ADR 0027, which covers summary content and display.

## Context

After the first real summaries, the user asked for the fewest words with the most value:
"对我没有任何效率提升的价值的东西我不要", for example full subjects. In the user's words, a
mail should show:
- as its title, only what it is about and its deadline;
- an importance mark;
- when opened, the distilled useful information first, then the original.

Low-value mail is collapsed and its count shown (the user's choice over hiding it
completely). Batch handling and chat come later (T-0027) and stay inside Personal OS.

## Decision

- **Prompt v2** (`prompts/email_summary.v2.toml`) returns:
  - `title`: at most 20 characters, what it is about plus the deadline;
  - `importance`: high/normal/low;
  - `low_value`;
  - `points`: 1 to 5 facts, empty for low-value mail;
  - `action_needed`, `action`, `deadline_text`, `deadline_date`.

  The output schema cuts the title to 20 characters and each point to 40, and keeps at
  most 5 points. Cutting costs no retry.
- **Storage.** `email_summary.gist` now holds the title. Migration 0012 adds `points`
  (JSON) and `low_value`.
- **Redo once.** Only after a model client opens, so with no key or budget the old
  summary stays visible: a summary made with an older prompt version is reset and redone once
  with the current one. That covered about 60 mails, roughly US$0.04. Skipped mails
  (sensitive, unreadable) are not redone, because no model was involved. After this
  each mail is summarised once, unless its sender, subject or body changes (ADR 0027).
- **A new 邮件 page:**
  - the list shows importance, the AI title, 需处理 and 未读; the original subject is shown
    only until a summary exists;
  - opening a mail shows points, then what to do, then the original text under a
    collapsed 「原文」 line;
  - low-value mail sits behind 「已收起 N 封没有价值的邮件」.

  The 连接 page now only says how many mails were synced and points to the 邮件 page.
- **今日:**
  - mail entries use the AI title;
  - low-value unread mail is left out of 未读邮件 and out of its count, and a line
    says how many were collapsed (`low_value_mail`);
  - 需要处理的邮件 never lists low-value mail.

## Consequences

- A summary from an older prompt is never shown as a title. Its gist is a long sentence,
  so the list and 今日 fall back to the subject until it is redone. Mail older than the
  summary window keeps its v1 summary until T-0026 widens the window.
- 今日's headline count now excludes low-value mail, so it can be lower than before.

- If the AI wrongly marks a mail low-value, it is one click away, not lost. That is why
  the user chose collapsing over hiding.
- Titles are capped by code as well as by the prompt, so a long title never reaches the
  list.
- `deadline_date` and the rules the user can give the AI arrive with the chat (T-0027).
  Backfilling all history is T-0026.

## Amendment 2026-11-11: prompt v3 and DeepSeek thinking off (T-0026)

Prompt v2 failed on 32 real mails: DeepSeek reasoned on its own and used up all
600 output tokens, leaving no answer. The fix:
- DeepSeek requests send `thinking: disabled`, unless a task sets `reasoning=True`;
- prompt v3 never copies URLs (it says 「链接见原文」 instead) and includes an example
  answer;
- links of 40 characters or more are replaced by 「[链接]」 before sending; the original
  text keeps them;
- a newer prompt redoes v1 summaries and older failures once. A good v2 summary is kept,
  and any v2+ gist counts as a title;
- a failure is stamped with its prompt version, so it never loops.

## Amendment 2026-11-11 (later): no collapsing (T-0028)

The user: "暂时不要把那些无用的折叠起来，就跟正常的邮件按时间顺序放好". Low-value mail is now
listed with all other mail, newest first, and marked 次要, both on the 邮件 page and in
今日's unread list. `low_value_mail` stays in the contract, always 0. 需要处理的邮件 still
leaves low-value mail out.
