"""DeepSeek through its OpenAI-compatible HTTP API, on stdlib urllib (ADR 0025).

No vendor SDK: one POST to `/chat/completions` in JSON mode. Error messages carry only
the HTTP status or the exception type, never the request or the key.
"""

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from apps.hub.models.provider import (
    JsonReply,
    JsonRequest,
    ProviderError,
    ProviderErrorKind,
    Usage,
)

DEFAULT_BASE_URL = "https://api.deepseek.com"
TIMEOUT_S = 60.0  # per socket operation
DEADLINE_S = 120.0  # for the whole response, even while the server sends keep-alive bytes
_CHUNK = 64 * 1024
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

_STATUS_KINDS = {
    400: ProviderErrorKind.bad_request,
    422: ProviderErrorKind.bad_request,
    401: ProviderErrorKind.auth,
    403: ProviderErrorKind.auth,
    402: ProviderErrorKind.no_balance,
    429: ProviderErrorKind.rate_limit,
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header (the key) to
    whatever host `Location` names. A 3xx comes back as an HTTPError instead."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def check_base_url(url: str) -> str:
    """https only, except plain http to this machine (the test stub)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url.rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return url.rstrip("/")
    raise ValueError("model base URL must be https (http only for 127.0.0.1)")


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def parse_usage(raw: Any) -> Usage | None:
    """Token counts, or None when the reply has no usable usage block."""
    if not isinstance(raw, dict):
        return None
    usage: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    hit = _int(usage.get("prompt_cache_hit_tokens"))
    miss = _int(usage.get("prompt_cache_miss_tokens"))
    prompt = _int(usage.get("prompt_tokens")) or hit + miss
    return Usage(
        input_tokens=max(prompt, hit + miss),
        cached_input_tokens=min(hit, prompt) if prompt else hit,
        output_tokens=_int(usage.get("completion_tokens")),
    )


class DeepSeekProvider:
    vendor = "deepseek"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = TIMEOUT_S,
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self.base_url = check_base_url(base_url)
        self.timeout_s = timeout_s
        self.deadline_s = deadline_s

    def complete_json(self, request: JsonRequest, api_key: str) -> JsonReply:
        body = json.dumps(
            {
                "model": request.model,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": request.max_output_tokens,
                "temperature": request.temperature,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        started = time.monotonic()
        try:
            with _OPENER.open(http_request, timeout=self.timeout_s) as response:
                chunks: list[bytes] = []
                # Silence is caught by the per-read timeout; a slow drip by this deadline.
                while chunk := response.read1(_CHUNK):
                    chunks.append(chunk)
                    if time.monotonic() - started > self.deadline_s:
                        raise TimeoutError("deadline")
                raw = b"".join(chunks)
        except urllib.error.HTTPError as exc:
            exc.close()
            kind = _STATUS_KINDS.get(exc.code)
            if kind is None:
                kind = (
                    ProviderErrorKind.transient
                    if exc.code >= 500
                    else ProviderErrorKind.bad_request  # 3xx (never followed) and other 4xx
                )
            raise ProviderError(kind, f"HTTP {exc.code}", status=exc.code) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as exc:
            # Conservative: a refused connection sent nothing, but a timeout may have billed.
            raise ProviderError(
                ProviderErrorKind.transient, type(exc).__name__, maybe_billed=True
            ) from None
        return _reply(raw)


def _reply(raw: bytes) -> JsonReply:
    try:
        data = json.loads(raw.decode("utf-8"))  # leading keep-alive blank lines are fine
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError(
            ProviderErrorKind.bad_output, "response is not JSON", maybe_billed=True
        ) from None
    if not isinstance(data, dict):
        raise ProviderError(
            ProviderErrorKind.bad_output, "response is not an object", maybe_billed=True
        )
    usage = parse_usage(data.get("usage"))  # pyright: ignore[reportUnknownMemberType]
    choices = data.get("choices")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    first: Any = choices[0] if isinstance(choices, list) and choices else {}
    message: Any = first.get("message", {}) if isinstance(first, dict) else {}  # pyright: ignore[reportUnknownMemberType]
    content: Any = message.get("content") if isinstance(message, dict) else None  # pyright: ignore[reportUnknownMemberType]
    finish: Any = first.get("finish_reason") if isinstance(first, dict) else None  # pyright: ignore[reportUnknownMemberType]
    request_id: Any = data.get("id")  # pyright: ignore[reportUnknownMemberType]
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
