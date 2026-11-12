"""Mail triage inside Personal OS (ADR 0034): an in-app 已处理 state, groups, rules.

The mailbox is never changed (ADR 0022). Nothing here is applied from model output alone:
a person clicks every batch.
"""

import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

TextField = Literal["sender", "sender_domain", "subject", "title"]  # title = the AI title
Flag = Literal["low_value", "action_needed", "importance_high", "importance_low", "deadline_past"]
MAX_BATCH = 1000


def normalize(text: str) -> str:
    """How rule values and mail text are compared: NFKC, case-folded, trimmed."""
    return unicodedata.normalize("NFKC", text).casefold().strip()


SECOND_LEVEL = {"com", "net", "org", "edu", "gov", "ac", "co"}


def base_domain(host: str) -> str:
    """ "g.joinhandshake.com" -> "joinhandshake.com"; "news.example.com.cn" ->
    "example.com.cn" (a two-letter country code under com/edu/... keeps three labels)."""
    labels = normalize(host).split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def is_bare_suffix(domain: str) -> bool:
    labels = domain.split(".")
    return len(labels) < 2 or (
        len(labels) == 2 and labels[0] in SECOND_LEVEL and len(labels[1]) == 2
    )


def _clean_value(value: str) -> str:
    value = normalize(value)
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("control characters are not allowed")
    if value.isascii() and len(value) < 3:
        raise ValueError("an ASCII value needs at least 3 characters")
    return value


class TextCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text"] = "text"
    field: TextField
    op: Literal["contains", "equals"] = "contains"  # plain text only: no patterns
    value: Annotated[str, Field(min_length=2, max_length=80), AfterValidator(_clean_value)]

    @model_validator(mode="after")
    def _not_a_whole_suffix(self) -> "TextCondition":
        # "com.cn" would match every sender under it through the subdomain rule.
        if self.field == "sender_domain" and is_bare_suffix(self.value):
            raise ValueError("a sender domain must name one sender, not a suffix like com.cn")
        return self


class FlagCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["flag"] = "flag"
    flag: Flag
    value: bool = True


Condition = Annotated[TextCondition | FlagCondition, Field(discriminator="kind")]


class Selector(BaseModel):
    """All conditions must hold (AND). Kept tiny on purpose: no regex, OR or wildcards."""

    model_config = ConfigDict(extra="forbid")
    all_of: Annotated[list[Condition], Field(min_length=1, max_length=4)]


class GroupKind(StrEnum):
    due_soon = "due_soon"
    overdue = "overdue"
    grades = "grades"
    course = "course"
    needs_action = "needs_action"
    sender = "sender"
    low_value = "low_value"
    unsummarised = "unsummarised"
    other = "other"


class TriageGroup(BaseModel):
    key: str  # "due_soon", "course:CIS D022A", "sender:joinhandshake.com"
    kind: GroupKind
    label: str
    count: int
    item_ids: list[str]
    rule: Selector | None  # set when 「以后也这样」 makes sense for this group
    rule_description: str


class HandledBy(StrEnum):
    batch = "batch"
    manual = "manual"
    rule = "rule"


class HandledMark(BaseModel):
    item_id: str
    by: HandledBy
    batch_id: str | None
    rule_id: str | None


class BatchStatus(StrEnum):
    applied = "applied"
    undone = "undone"


class TriageBatch(BaseModel):
    id: str
    kind: str  # "group" | "manual"
    status: BatchStatus
    label: str
    description: str
    count: int
    item_ids: list[str]
    rule_id: str | None
    applied_at: datetime | None
    undone_at: datetime | None
    version: int


class TriageRule(BaseModel):
    id: str
    name: str
    selector: Selector
    description: str
    enabled: bool
    matched: int  # open (unhandled-by-hand) mails it covers now
    created_at: datetime
    version: int


class TriageView(BaseModel):
    open_count: int  # unread and not handled: the 「未处理」 number
    unread_count: int
    unsummarised: int
    groups: list[TriageGroup]
    handled: list[HandledMark]
    recent: list[TriageBatch]  # the last 10, for 撤销
    rules: list[TriageRule]


class HandleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_BATCH)]
    group_key: Annotated[str, Field(max_length=120)] = ""
    save_rule: bool = False  # only with a group that offers a rule; the server builds it


class ItemHandled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handled: bool


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
