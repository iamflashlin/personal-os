# 0028 - Multi-model AI platform plan; LiteLLM (litellm-core) behind the model door

- Status: accepted (the user, 2026-11-11)
- Builds on ADR 0025 (model layer) and ADR 0026 (phase 6). Card: T-0024.

## Context

On 2026-11-11 the user set out how Personal OS should use AI models. The platform should:
- route every call through one gateway, with vendor adapters, permissions, logs and cost;
- keep a model registry (prices, capabilities, test results);
- run benchmarks, scored on accuracy and misses, quality, effective task cost, stability
  and speed, with hard gates for privacy and high-risk errors. Effective task cost
  counts calls, retries, escalations and human correction;
- give each workflow a fixed primary model, a fallback and conditions for escalating. A
  config file comes first; dynamic routing waits for real data;
- give every model the same memory through a memory gateway. Memory belongs to Personal
  OS; models get only what a task needs and submit memory candidates, which are checked
  before they are written;
- monitor cost and quality.

Chinese and international models compete on equal terms, on verifiable official
information and test results.

## Decisions (the user's answers)

1. **When:** first run the DeepSeek email summaries on real mail, alongside the phase 3
   cards. Then run the first multi-model benchmark, on email summaries.
2. **Benchmark data: real email.** Each candidate vendor sees real mail only after the
   user agrees to that vendor: account, key, money and privacy terms, asked one vendor at
   a time.
3. **LiteLLM: now.** The lighter `litellm-core` distribution was preferred and has been
   verified.

## LiteLLM details (T-0024)

- **Package:** `litellm-core==1.106.6`. It is MIT-licensed and was uploaded 2026-10-28,
  at least 14 days old. It comes from the BerriAI/litellm repo via Trusted Publishing.
- **Why core:** it uses the same SDK sources and the `litellm` import, without boto3,
  tokenizers or huggingface-hub. It still pulls in openai, httpx, aiohttp, tiktoken,
  jinja2, jsonschema and their dependencies. Release 1.107.0 was yanked upstream with no
  reason given; we are not affected.
- **Security:** of the 18 GitHub advisories in 2026, nearly all concern the LiteLLM proxy
  server (admin UI, SSO, MCP, guardrails). We do not run the proxy. No compromise of the
  PyPI package was found.
- **Placement:** LiteLLM sits only inside `apps/hub/models/litellm_adapter.py`, behind
  `ModelProvider`. `models.service` keeps every guarantee from ADR 0025: budget before
  the call, a cost row at our own dated peak prices from `pricing.py`, the key from
  Credential Manager, no text stored. LiteLLM's own cost figure is not used.
- **Hardening** (each item has a test or a recorded spike result):
  - LiteLLM's loggers are capped at WARNING on every call. At DEBUG it prints every prompt
    (the full email) and every raw response.
  - `LITELLM_LOCAL_MODEL_COST_MAP=True` is forced when the adapter module is imported,
    before litellm, and overrides any value in the environment. The bundled cost map is
    used and nothing is downloaded. A test in a fresh interpreter blocks every
    non-loopback connection and passes.
  - `num_retries=0`, because a hidden retry would be a second billed call that the cost
    log would not see.
  - Redirects are never followed. LiteLLM's default HTTP client follows them: the spike
    shows a 307 resending the POST, prompt included, to the other host. So every call
    passes its own `HTTPHandler(follow_redirects=False)`. Tests cover 301/302/307/308
    with a stub that records any method, and they fail when the setting is switched
    back.
  - Each call has a 120 s total deadline on top of httpx's 60 s per-read timeout. The
    call runs in a worker thread, and past the deadline its HTTP client is closed. A
    test with a 0.5 s deadline ends a 2 s response early.
  - Error messages carry only the exception type and HTTP status.
- **Error mapping:**
  - auth / permission → `key_rejected`;
  - rate limit → `rate_limited`;
  - HTTP 402 → `no_balance`;
  - timeout / connection / deadline → transient, maybe billed. This deliberately
    includes a refused connection and unknown errors raised before sending, which
    billed nothing;
  - 5xx → transient;
  - 2xx with an unreadable body → bad output, maybe billed;
  - other statuses → bad request.
- **Code removed:** the hand-written urllib DeepSeek adapter. The same test suite now
  runs against the LiteLLM provider.

## Consequences

- Adding a vendor means a price entry in `pricing.py` (source and date), a base URL and a
  key name. The registry and benchmark cards will formalise this.
- The dependency tree grows, but stays on drive D (uv cache in `D:\dev-cache`). Upgrading
  LiteLLM is a reviewed card: re-run the spike and the model suite against the new
  version.
- The first call pays LiteLLM's import time (about a second) inside its measured
  latency. This is accepted.
- Importing litellm sets the `httpx` logger to WARNING. This is harmless.
- 未验证: a live call through LiteLLM to api.deepseek.com, via `scripts/verify/models.py
  --live`, once the user has entered the key and agreed.
