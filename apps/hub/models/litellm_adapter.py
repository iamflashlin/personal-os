"""Model vendors through LiteLLM (ADR 0028), behind the same `ModelProvider` door.

LiteLLM only translates and sends the request. Everything that protects the user stays in
`models.service`: the budget check before the call, the cost row at our own dated peak
prices, the key from Credential Manager.

Hardening, all checked by tests:
- LiteLLM's loggers are capped at WARNING. Its DEBUG output prints every prompt (the full
  email) and every raw response.
- The model cost map is the copy bundled with the package (no fetch from api.litellm.ai),
  and our cost comes from `pricing.py` anyway.
- No retries inside LiteLLM: a retry is a second billed call that `models.service` would
  not see. Retries belong to the caller.
- Redirects are never followed. LiteLLM's default HTTP client follows them, and a 307/308
  would POST the whole prompt (the email) to whatever host `Location` names, so every
  call gets our own client with `follow_redirects=False`.
- A total deadline per call (not only httpx's per-read timeout): a server that drips one
  byte at a time cannot hold a call, and its budget reservation, open for long.
- The first call pays LiteLLM's import time (about a second) inside its latency.
"""

import concurrent.futures
import logging
import os
import urllib.parse
from typing import Any

# Before anything can import litellm: use the bundled cost map, never download one. This
# overrides a value from the environment on purpose.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from apps.hub.models.provider import (
    JsonReply,
    JsonRequest,
    ProviderError,
    ProviderErrorKind,
    ToolCall,
    ToolReply,
    ToolRequest,
    Usage,
)

TIMEOUT_S = 60.0  # per connect / read / write (httpx)
DEADLINE_S = 120.0  # for the whole call
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm")
_BASE_URLS = {"deepseek": "https://api.deepseek.com"}


def check_base_url(url: str) -> str:
    """https only, except plain http to this machine (the test stub)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url.rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return url.rstrip("/")
    raise ValueError("model base URL must be https (http only for 127.0.0.1)")


def _litellm() -> Any:
    """Import LiteLLM quietly (it is slow to import, so only when a call is made).

    The logger caps are applied on every call, not once, so a later change of logging
    configuration elsewhere cannot switch LiteLLM's prompt-printing DEBUG output back on.
    """
    import litellm

    # Module flags; set by name because not all of them are typed exports.
    for flag, value in (
        ("suppress_debug_info", True),
        ("set_verbose", False),
        ("telemetry", False),
    ):
        setattr(litellm, flag, value)
    for name in _LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return litellm


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _usage(raw: Any) -> Usage | None:
    """Token counts, or None when the vendor reported none (LiteLLM then fills zeros)."""
    if raw is None:
        return None
    prompt = _int(getattr(raw, "prompt_tokens", 0))
    output = _int(getattr(raw, "completion_tokens", 0))
    details = getattr(raw, "prompt_tokens_details", None)
    cached = _int(getattr(details, "cached_tokens", 0)) or _int(
        getattr(raw, "prompt_cache_hit_tokens", 0)
    )
    if prompt == 0 and output == 0:
        return None
    return Usage(input_tokens=prompt, cached_input_tokens=min(cached, prompt), output_tokens=output)


def _error(exc: Exception, litellm: Any) -> ProviderError:
    """Map LiteLLM's exceptions; the message is only the type and status, never the text."""
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    label = f"{type(exc).__name__} HTTP {status}" if status else type(exc).__name__
    if isinstance(exc, litellm.Timeout | litellm.APIConnectionError):
        return ProviderError(ProviderErrorKind.transient, label, maybe_billed=True)
    if isinstance(exc, litellm.AuthenticationError | litellm.PermissionDeniedError):
        return ProviderError(ProviderErrorKind.auth, label, status=status)
    if isinstance(exc, litellm.RateLimitError):
        return ProviderError(ProviderErrorKind.rate_limit, label, status=status)
    if status == 402:
        return ProviderError(ProviderErrorKind.no_balance, label, status=status)
    if status is not None and 200 <= status < 300:
        # The vendor answered "OK" but LiteLLM could not read the body: it may have billed.
        return ProviderError(ProviderErrorKind.bad_output, label, maybe_billed=True)
    if status is not None and status >= 500:
        return ProviderError(ProviderErrorKind.transient, label, status=status)
    if status is not None or isinstance(exc, litellm.BadRequestError):
        return ProviderError(ProviderErrorKind.bad_request, label, status=status)
    return ProviderError(ProviderErrorKind.transient, label, maybe_billed=True)


class LiteLLMProvider:
    """One vendor (e.g. "deepseek") reached through LiteLLM's `<vendor>/<model>` names."""

    def __init__(
        self,
        vendor: str,
        base_url: str | None = None,
        timeout_s: float = TIMEOUT_S,
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self.vendor = vendor
        self.base_url = check_base_url(base_url or _BASE_URLS[vendor])
        self.timeout_s = timeout_s
        self.deadline_s = deadline_s

    def complete_json(self, request: JsonRequest, api_key: str) -> JsonReply:
        litellm = _litellm()
        import httpx
        from litellm.llms.custom_httpx.http_handler import HTTPHandler

        # One client per call: no redirects, and closing it ends a call past its deadline.
        http = HTTPHandler(timeout=httpx.Timeout(self.timeout_s), follow_redirects=False)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._send, litellm, http, request, api_key)
            try:
                response: Any = future.result(timeout=self.deadline_s)
            except concurrent.futures.TimeoutError:
                http.close()  # makes the stuck request fail in its thread
                raise ProviderError(
                    ProviderErrorKind.transient, "deadline", maybe_billed=True
                ) from None
            except ProviderError:
                raise
            except Exception as exc:
                raise _error(exc, litellm) from None
        finally:
            pool.shutdown(wait=False)
            http.close()
        return _reply(response)

    def complete_tools(self, request: ToolRequest, api_key: str) -> ToolReply:
        """One tool-calling turn, sent as plain OpenAI-compatible HTTP with httpx (ADR 0036):
        litellm-core imports its MCP handler whenever `tools` is passed, and that needs the
        `mcp` package, which is not installed. Same timeouts, no redirects, same mapping."""
        import httpx

        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}, *request.messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if self.vendor == "deepseek":
            body["thinking"] = {"type": "disabled"}
        url = self.base_url.rstrip("/") + "/chat/completions"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_s, read=self.deadline_s),
                follow_redirects=False,
            ) as http:
                response = http.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"})
        except httpx.TimeoutException:
            raise ProviderError(ProviderErrorKind.transient, "timeout", maybe_billed=True) from None
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.transient, type(exc).__name__, maybe_billed=True
            ) from None
        return _tool_reply(response.status_code, response)

    def _reasoning_params(self, request: JsonRequest) -> dict[str, Any]:
        """DeepSeek reasons on its own for harder inputs; switch it off unless asked for."""
        if self.vendor == "deepseek" and not request.reasoning:
            return {"thinking": {"type": "disabled"}}
        return {}

    def _send(self, litellm: Any, http: Any, request: JsonRequest, api_key: str) -> Any:
        return litellm.completion(
            model=f"{self.vendor}/{request.model}",
            api_base=self.base_url,
            api_key=api_key,
            messages=[
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            response_format={"type": "json_object"},
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            **self._reasoning_params(request),
            timeout=self.timeout_s,
            num_retries=0,
            max_retries=0,
            client=http,
        )


def _http_error(status: int) -> ProviderError:
    label = f"HTTP {status}"
    if status in (401, 403):
        return ProviderError(ProviderErrorKind.auth, label, status=status)
    if status == 402:
        return ProviderError(ProviderErrorKind.no_balance, label, status=status)
    if status == 429:
        return ProviderError(ProviderErrorKind.rate_limit, label, status=status)
    if status >= 500:
        return ProviderError(ProviderErrorKind.transient, label, status=status)
    return ProviderError(ProviderErrorKind.bad_request, label, status=status)


def _tool_reply(status: int, response: Any) -> ToolReply:
    if status != 200:
        raise _http_error(status)
    try:
        data = response.json()
        first = data["choices"][0]
        message = first["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ProviderError(
            ProviderErrorKind.bad_output, "unreadable reply", maybe_billed=True
        ) from None
    raw = data.get("usage") or {}
    usage = Usage(
        int(raw.get("prompt_tokens") or 0),
        int(raw.get("prompt_cache_hit_tokens") or 0),
        int(raw.get("completion_tokens") or 0),
    )
    calls: list[ToolCall] = []
    for c in message.get("tool_calls") or []:
        fn = (c or {}).get("function") or {}
        if isinstance(fn.get("name"), str) and isinstance(c.get("id"), str):
            calls.append(ToolCall(c["id"], fn["name"], str(fn.get("arguments") or "{}")))
    content = message.get("content")
    request_id = data.get("id")
    return ToolReply(
        content=content if isinstance(content, str) else "",
        tool_calls=calls,
        usage=usage,
        finish_reason=str(first.get("finish_reason") or ""),
        request_id=request_id[:100] if isinstance(request_id, str) else "",
    )


def _reply(response: Any) -> JsonReply:
    usage = _usage(getattr(response, "usage", None))
    choices = getattr(response, "choices", None) or []
    first = choices[0] if choices else None
    message = getattr(first, "message", None)
    content = getattr(message, "content", None)
    finish = getattr(first, "finish_reason", None)
    request_id = getattr(response, "id", None)
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(
            ProviderErrorKind.bad_output, "empty content", maybe_billed=True, usage=usage
        )
    return JsonReply(
        text=content,
        usage=usage,
        finish_reason=finish if isinstance(finish, str) else "",
        request_id=request_id[:100] if isinstance(request_id, str) else "",
    )
