"""What a model vendor adapter must provide. Business code never sees a vendor."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderErrorKind(StrEnum):
    auth = "auth"
    no_balance = "no_balance"
    rate_limit = "rate_limit"
    transient = "transient"
    bad_request = "bad_request"
    bad_output = "bad_output"


@dataclass(frozen=True)
class Usage:
    input_tokens: int  # all prompt tokens, cached ones included
    cached_input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class JsonRequest:
    model: str
    system: str
    user: str
    max_output_tokens: int
    temperature: float = 0.0
    # Off unless a task needs it: a vendor's hidden reasoning spends the output budget, and
    # DeepSeek thinks on its own for harder inputs until max_tokens leaves no answer.
    reasoning: bool = False


@dataclass(frozen=True)
class JsonReply:
    text: str
    usage: Usage | None  # None when the vendor sent no usable usage block
    finish_reason: str
    request_id: str


class ProviderError(Exception):
    """A vendor call that did not return usable output.

    The message carries only a status and an exception type, never the request, so it
    can be stored and logged.
    """

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        status: int | None = None,
        maybe_billed: bool = False,
        usage: Usage | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.maybe_billed = maybe_billed  # the vendor may have run it (e.g. a timeout)
        self.usage = usage  # what the vendor reported as billed, when it said


class ModelProvider(Protocol):
    vendor: str

    def complete_json(self, request: JsonRequest, api_key: str) -> JsonReply: ...
