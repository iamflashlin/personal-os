"""Facts about one mail, and the tiny rule language that matches them (ADR 0034).

Text conditions are plain substring or equality after NFKC + casefold: no regex, so a
value like ".*" only matches those two characters.
"""

from dataclasses import dataclass
from datetime import date, datetime

from packages.contracts.summaries import EmailSummary
from packages.contracts.triage import (
    FlagCondition,
    Selector,
    TextCondition,
    base_domain,
    normalize,
)

FIELD_LABEL = {
    "sender": "发件人",
    "sender_domain": "发件域名",
    "subject": "主题",
    "title": "AI 标题",
}
FLAG_LABEL = {
    "low_value": "次要邮件",
    "action_needed": "需要处理",
    "importance_high": "重要",
    "importance_low": "不重要",
    "deadline_past": "截止已过",
}


@dataclass(frozen=True)
class MailFacts:
    item_id: str
    received: datetime | None
    sender_name: str
    sender_address: str
    subject: str
    seen: bool
    summary: EmailSummary | None  # a fresh `ok` summary, else None

    @property
    def domain(self) -> str:
        """The sender's base domain: "g.joinhandshake.com" -> "joinhandshake.com", so one
        sender's subdomains form one group (a "sender_domain equals" rule covers them)."""
        return base_domain(self.sender_address.rpartition("@")[2])

    @property
    def low(self) -> bool:
        s = self.summary
        return bool(s and (s.low_value or s.importance.value == "low"))


def _text(field: str, f: MailFacts) -> str:
    if field == "sender":
        return normalize(f"{f.sender_name} {f.sender_address}")
    if field == "sender_domain":
        return normalize(f.sender_address.rpartition("@")[2])  # the full host
    if field == "subject":
        return normalize(f.subject)
    return normalize(f.summary.gist) if f.summary else ""


def _flag(flag: str, f: MailFacts, today: date) -> bool:
    s = f.summary
    if s is None:
        return False
    if flag == "low_value":
        return f.low
    if flag == "action_needed":
        return s.action_needed
    if flag == "importance_high":
        return s.importance.value == "high"
    if flag == "importance_low":
        return s.importance.value == "low"
    return bool(s.deadline_date and s.deadline_date < today)  # deadline_past


def _holds(c: TextCondition | FlagCondition, f: MailFacts, today: date) -> bool:
    if isinstance(c, FlagCondition):
        return _flag(c.flag, f, today) == c.value
    text = _text(c.field, f)
    if c.op == "contains":
        return c.value in text
    if c.field == "sender_domain":  # "example.com" also matches "mail.example.com"
        return text == c.value or text.endswith("." + c.value)
    return text == c.value


def matches(selector: Selector, f: MailFacts, today: date) -> bool:
    return all(_holds(c, f, today) for c in selector.all_of)


def describe(selector: Selector) -> str:
    """What a rule does, in Chinese, written by code (never by a model)."""
    parts: list[str] = []
    for c in selector.all_of:
        if isinstance(c, FlagCondition):
            label = FLAG_LABEL[c.flag]
            parts.append(label if c.value else f"不是{label}")
        else:
            verb = "包含" if c.op == "contains" else "是"
            parts.append(f"{FIELD_LABEL[c.field]}{verb}「{c.value}」")
    return "并且".join(parts)
