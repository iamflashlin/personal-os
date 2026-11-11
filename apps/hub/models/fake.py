# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""A deterministic provider for tests and offline verification (HANDOFF §4.4).

It answers with JSON built from the request, and markers in the user text make it fail:
`[fake:bad-json]`, `[fake:500]`, `[fake:401]`, `[fake:402]`, `[fake:429]`.
If `POS_FAKE_MODEL_LOG` names a file, every user text it receives is appended there, so a
verification script in another process can prove what was (not) sent.
"""

import json
import os
import re

from apps.hub.models.provider import (
    JsonReply,
    JsonRequest,
    ProviderError,
    ProviderErrorKind,
    Usage,
)

LOG_ENV = "POS_FAKE_MODEL_LOG"
_SUBJECT = re.compile(r"^(?:Subject|主题)[:：]\s*(.+)$", re.MULTILINE)
_FAILURES = {
    "[fake:500]": (ProviderErrorKind.transient, 500),
    "[fake:401]": (ProviderErrorKind.auth, 401),
    "[fake:402]": (ProviderErrorKind.no_balance, 402),
    "[fake:429]": (ProviderErrorKind.rate_limit, 429),
}


def _tokens(text: str) -> int:
    """A stand-in count: about one token per 3 UTF-8 bytes, never zero."""
    return max(1, len(text.encode("utf-8")) // 3)


class FakeProvider:
    vendor = "fake"

    def __init__(self) -> None:
        self.calls: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, api_key: str) -> JsonReply:
        self.calls.append(request)
        log = os.environ.get(LOG_ENV)
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(request.user + "\n---\n")
        for marker, (kind, status) in _FAILURES.items():
            if marker in request.user:
                raise ProviderError(kind, f"HTTP {status}", status=status)
        usage = Usage(_tokens(request.system + request.user), 0, 40)
        if "[fake:bad-json]" in request.user:
            raise ProviderError(ProviderErrorKind.bad_output, "response is not JSON", usage=usage)
        match = _SUBJECT.search(request.user)
        subject = match.group(1).strip() if match else request.user.strip()[:40]
        lowered = request.user.lower()
        action_needed = "截止" in request.user or "due" in lowered
        low_value = any(w in lowered for w in ("digest", "newsletter", "weekly", "促销"))
        body = request.user.split("\n\n", 1)[-1].replace("</email>", "").strip()
        text = json.dumps(
            {
                # Both shapes: prompt v1 read "gist", prompt v2 reads "title" and "points".
                "gist": f"（测试摘要）{subject}",
                "title": f"（测试摘要）{subject}",
                "low_value": low_value,
                "points": [] if low_value else [f"要点：{body[:24]}"],
                "action_needed": action_needed,
                "action": "按时提交" if action_needed else "",
                "deadline_text": "",
                "deadline_date": None,
                "importance": "high" if action_needed else "normal",
            },
            ensure_ascii=False,
        )
        return JsonReply(text=text, usage=usage, finish_reason="stop", request_id="fake")
