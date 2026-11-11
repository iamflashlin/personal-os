# 0025 - Model layer: DeepSeek through one ModelProvider door, with a cost log and a monthly cap

- Status: accepted (user decisions 2026-11-11)
- Card: T-0021. T-0022 (email summaries) and T-0023 (UI) build on it.

## Context

The user wants their email summarised so they do not have to read it. This is the first
feature that calls a language model. HANDOFF §4.4 asks for a `ModelProvider` door, a fake
provider for tests, versioned prompts and one `ModelCall` record per call.

The user's decisions, made 2026-11-11:
- **Vendor:** DeepSeek. The user said "只是处理邮件，用不到什么推理能力" and declined the
  Claude options.
- **Content sent:** the full email text, after verification-code and password-reset mail
  is filtered out.
- **Privacy, confirmed twice:**
  1. after being told DeepSeek stores data in the PRC;
  2. after being told its privacy policy allows training on user data, with opt-out only by
     emailing privacy@deepseek.com. The user answered "直接用", with no opt-out.
- **Cap:** US$10 a month. At the cap, summaries stop and the page says so.
- **Key:** the user creates the API key themselves; it is entered in the web UI and kept in
  keyring.

## Decision

- **Module.** `apps/hub/models` holds:
  - `provider.py` (the protocol and its error kinds);
  - `deepseek.py` (adapter);
  - `fake.py` (`FakeProvider`);
  - `pricing.py`;
  - `prompts.py` (loads `prompts/<name>.v<N>.toml`);
  - `models.py` (`model_call` table);
  - `service.py` (budget and `ModelClient`).
  Business code calls only `ModelClient.call_json(prompt, variables, OutputModel)`.
- **No new dependency.** The adapter uses stdlib `urllib` against the OpenAI-compatible
  `POST https://api.deepseek.com/chat/completions` in JSON mode (`response_format`
  json_object). httpx is only a dev dependency, and the Canvas connector already uses
  urllib. The base URL must be https; plain http is allowed only for 127.0.0.1, which the
  test stub uses.
- **Model and prices.** The model is `deepseek-flash`, with the price table read from the
  DeepSeek pricing page on 2026-11-11 (source and date are in `pricing.py`). Cost is
  always computed at **peak** rates, so the record never undercounts. Money is integer
  micro-USD, rounded up. A model without a price cannot be called.
- **Upper-bound estimate.** The estimate before each call is
  `(UTF-8 bytes of system + user + 64) × input price + max_tokens × output price`. A
  byte-level BPE token is at least one byte, and `max_tokens` caps all output.
- **Reserve, then settle.** The reservation inserts the row first and then checks the
  month's sum (which includes it), so concurrent reservations are serialised. This holds
  even across processes, because the INSERT takes SQLite's write lock. No lock is held
  during the HTTP call.
  1. Write the row as `reserved` at the estimate. If this UTC calendar month's recorded
     cost now exceeds the cap, roll back and raise `ModelUnavailable("budget")`, before
     any HTTP request.
  2. After the call, update the row to `ok` or `error`:
     - `ok` is charged at the actual cost. If the reply has no usable usage block, it is
       charged at the estimate instead, so an unreadable usage field never makes a billed
       call look free.
     - An error costs 0 when the vendor answered with an error status.
     - An error keeps the estimate on a timeout, a connection error, an unexpected
       exception or a 200 with unusable content, because the vendor may have billed.
       This deliberately includes a refused connection, which billed nothing.
  3. A cost above the estimate is logged and flagged as `over_estimate` in the audit
     detail, so a broken upper-bound assumption (for example, reasoning tokens outside
     `max_tokens`) is visible.

  A crash mid-call therefore still counts against the budget.
- **Transport.**
  - Redirects are never followed: urllib would resend the `Authorization` header to the
    new host. A 3xx is a non-retryable error.
  - The whole response has a 120 s deadline on top of the 60 s socket timeout, so a
    server that keeps sending keep-alive bytes cannot hang a call.
  - The key is kept out of `ModelClient`'s `repr`.
- **Errors.**
  - 401/403 → `key_rejected`, 402 → `no_balance`, 429 → `rate_limited`. These raise
    `ModelUnavailable`, because trying the next email will not help.
  - 5xx, timeouts and bad output raise `ModelFailed(retryable=True)`.
  - 400/422 raise `ModelFailed(retryable=False)`.
- **What is stored.** `model_call` keeps vendor, model, purpose, ref, prompt
  name/version/sha, tokens, estimate, cost, latency, finish reason and request id. It
  never keeps prompt or email text, and it never keeps the key. Each call also writes
  one audit event with the same numbers.
- **Key.** It lives in keyring under credential name `deepseek` (existing credentials
  module, ADR 0018). It is revealed once per `open_client`, which is audited. A missing
  key → `ModelUnavailable("no_key")` with no request.
- **Settings.**
  - `POS_MODEL_PROVIDER` = `deepseek` | `fake`
  - `POS_MODEL_NAME`, default `deepseek-flash`
  - `POS_MODEL_BASE_URL`
  - `POS_AI_BUDGET_USD`, default 10, must be > 0

## Consequences

- A budget refusal writes no row, so `ModelUsage.last_error` never says "budget". The UI
  (T-0023) shows the budget state from spent vs. budget instead.

- Switching vendors means writing one adapter and adding its prices. Nothing else changes.
- The budget is recorded spend at peak rates. The real bill should be lower, never
  higher, except for calls made outside the Hub, such as the `--live` verification on a
  throwaway database. Each live log prints its own cost.
- 未验证 until the first live call:
  - that the model id `deepseek-flash` is accepted;
  - that JSON mode works with it;
  - the usage field names (`prompt_cache_hit_tokens` / `_miss_tokens`);
  - whether reasoning tokens are on by default;
  - that api.deepseek.com is reachable from this PC.

  Spike: `uv run python scripts/verify/models.py --live`, which takes about 15 minutes and
  costs under US$0.001. It runs after the user enters the key and agrees to the run.
