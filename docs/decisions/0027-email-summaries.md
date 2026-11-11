# 0027 - AI email summaries: one per mail, sensitive mail never sent

- Status: accepted (user decisions 2026-11-11, recorded in ADR 0025)
- Card: T-0022. T-0023 adds the web UI. Phase 6 of ADR 0026; the user asked to finish it
  before returning to phase 3.

## Context

The user does not want to read their mail. The model layer (ADR 0025) can now call
DeepSeek within a US$10 monthly cap. The user agreed to send the full text of each mail,
except verification-code and password-reset mail.

## Decision

- **Own table and module.** `apps/hub/summaries` owns `email_summary`: one row per
  (owner, synced mail), deleted with the mail by a foreign-key cascade. Summaries are not
  columns on `synced_item`, for three reasons:
  - that row is the sync's source of truth, and its `content_hash` is the sync's change
    test;
  - AI output has its own lifecycle (status, attempts, next try, prompt version, link to
    the `model_call` row);
  - summaries must be removable or regenerable without touching synced data.

  The module reads mail only through `integrations.service.items_between`, and calls the
  model only through `models.service`.
- **What a summary depends on.** It depends on the sender address, subject and body. If
  they change, the row goes back to `pending`. The read state does not count, so reading
  a mail elsewhere costs nothing.
- **Never sent.**
  - Mail in which `summaries/sensitive.py` finds a one-time code or password-reset
    wording becomes `skipped_sensitive`. The filter covers Chinese and English terms,
    OTP/2FA/MFA as words, and "code"/"码" shortly before 4-8 digits.
  - Unparsable mail and empty bodies become `skipped_unreadable`.
  - Both checks need no key and no model, so the user can see what will be skipped before
    entering a key.
  - The filter deliberately over-filters: a false positive costs one summary, while a
    false negative would send a live code to a third party.
  - The stored skip reason is a fixed label for the rule that matched, never the matched
    text, which could contain the code itself.
  - Digit boundaries are written as `(?<!\d)`/`(?!\d)`, because Python's `\b` treats CJK
    characters as word characters and would miss "您的码是482913请勿泄露".
- **Prompt delimiters.** `<email>`/`</email>` in any mail-controlled value are replaced
  with `[email-tag]`, so a mail cannot close the block early and pose as the operator.
- **What is sent.** Sender name and address, subject, receive time, attachment names and
  the stored body (≤ 8,000 characters, per ADR 0022). Recipients are never sent. The
  prompt wraps the mail in `<email>` and says its content is data, not instructions.
  The output is display text only and triggers nothing.
- **When it runs.** A `summaries.email` job:
  - runs after every successful sync, with idempotency key
    `summaries.email:after:<sync job id>` so a retried sync queues one run;
  - runs on `POST /summaries/run`, for example right after the key is entered;
  - has no schedule of its own, because the syncs already run on schedules.
- **One run.**
  - It covers mail received in the last 14 days and handles at most 20 due mails, oldest
    first, within 150 s. It queues a continuation when more mail is due.
  - It holds no database transaction across a model call, because the call writes
    `model_call` rows.
- **Failures.**
  - No key, a rejected key, no balance, a rate limit or the monthly budget stops the run
    and leaves mail `pending` without counting an attempt.
  - A transient error or bad output retries after 5, then 10 minutes, and the mail becomes
    `failed` at the third attempt. A bad request fails at once.
  - Anything else that stops a run is logged, e.g. an unpriced model.
- **Status for the UI.** `GET /summaries/status` returns the pending count, a derived
  `blocked` reason (`no_key`, `key_rejected`, `no_balance`, `rate_limited`, `budget`)
  and a Chinese notice. The reason is `budget` when a pending mail's upper-bound estimate
  exceeds what is left this month. `GET /models/usage` returns the month's spend.
- **FakeProvider.** With `POS_MODEL_PROVIDER=fake` the model name is `fake`, which has its
  own price entry, so offline verification needs no settings beyond the provider.

## Consequences

- Retries and the month rollover wait for the next sync, at most one sync interval away.
  `POST /summaries/run` forces a run.
- 未验证: how much of the user's real 163 mail the filter catches. Spike (≤ 15 min): once
  163 is connected and before the key is entered, the user looks over 最近邮件. Every
  skipped mail is labelled; an OTP mail still `pending` is a miss to add to the test
  samples.
