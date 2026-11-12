# 0033: Questions about mail, answered from stored summaries

Status: accepted (2026-11-11). D1: the user agreed: "我同意把问题和总结发给deepseek".

## Context
The user wants a chat window: ask questions about their mail, and later give batch rules
(mailbox stays read-only, ADR 0022). This record covers the questions only. Batch rules
need a new table and get their own decision.

## Decision
- `POST /chat/ask` in a new Hub module `apps/hub/chat`. It reads only through
  `integrations.service` (`item_heads`, which loads no bodies, and `items_by_id` for the at
  most 8 cited mails) and `summaries.service` (`ok_summaries`, `count`). The model call
  goes through `models.service`, so the monthly cap, the `model_call` rows, the audited key
  reveal and the error mapping are the same as for summaries.
- **Stateless.** The browser keeps the conversation and sends the last 6 turns. The
  question is stored nowhere: `model_call.ref` is `""`, and the Hub log has no text. One
  `credential.reveal` audit row is written per question.
- **What is sent (D1).** For at most 60 mails: date, sender, subject, and the AI title,
  points, action, deadline and importance. Also sent: the question and recent turns. No
  mail body is sent. Mail that is sensitive, unreadable, pending, failed, or changed since
  its summary is not sent at all, not even its subject.
- **Retrieval** without embeddings or new dependencies:
  - ASCII words plus CJK character pairs, scored by IDF; the previous question counts at
    half weight;
  - the 20 newest mails and up to 10 mails due from yesterday to 14 days ahead are always
    included.
- **Prompt injection.** Text from mail and the user is defanged: section tags become
  `[tag]`, and line breaks become spaces. The prompt says this text is data. Citations are
  filtered to the refs given (at most 8). The answer is plain text that triggers nothing,
  and the cited mails are shown so the user can check them. The prompt forbids doing
  homework (the CLAUDE.md CIS rule).
- **Errors.** `ModelUnavailable` → 503 with a Chinese sentence and the header
  `X-Model-Unavailable: <reason>`. `ModelFailed` → 502 ("请再问一次" when retryable).
- **Budget (D2).** Chat shares the US$10 monthly cap with summaries.

## Consequences
- One question costs roughly US$0.002–0.005 on DeepSeek (an estimate, 未验证). Spike: ask
  three real questions and read `/models/usage` (≤30 min).
- Mail that is not summarised yet cannot be found; the answer reports how many.
- Retrieval quality on real mail is 未验证. Spike (≤1 h, no model call): run `select()`
  over a copy of the database with ten typical questions.
