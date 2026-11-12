# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Open mail, grouped by code from the summary fields: no model call (ADR 0034).

Every mail lands in exactly one group (first match wins), so the counts add up.
"""

import re
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta

from apps.hub.triage.rules import MailFacts, describe
from packages.contracts.triage import (
    FlagCondition,
    GroupKind,
    Selector,
    TextCondition,
    TriageGroup,
    normalize,
)

SOON_DAYS = 7
SENDER_GROUP_MIN = 5
GRADE_WORDS = ("成绩", "分数", "已评分", "评分已", "grade", "graded", "score")
_COURSE = re.compile(r"\b([A-Z]{2,5})\s+([A-Z]?\d{3,4}[A-Z]?)\b")


def course_keys(codes: list[str]) -> list[str]:
    """ "F26 CIS D022A 54Y Beg Prog …" -> "CIS D022A": the part mail senders also carry."""
    keys: list[str] = []
    for code in codes:
        m = _COURSE.search(code)
        if m and (key := f"{m.group(1)} {m.group(2)}") not in keys:
            keys.append(key)
    return keys


def _course(f: MailFacts, keys: list[str]) -> str | None:
    text = normalize(f"{f.sender_name} {f.subject}")
    return next((k for k in keys if normalize(k) in text), None)


def _is_grade(f: MailFacts) -> bool:
    text = normalize(f"{f.subject} {f.summary.gist if f.summary else ''}")
    return any(w in text for w in GRADE_WORDS)


def group(facts: list[MailFacts], today: date, codes: list[str]) -> list[TriageGroup]:
    """Groups of `facts` (already filtered to open mail), newest first inside each group."""
    keys = course_keys(codes)
    low_domains = Counter(f.domain for f in facts if f.summary and f.low and f.domain)
    big = {d for d, n in low_domains.items() if n >= SENDER_GROUP_MIN}

    def pick(f: MailFacts) -> tuple[str, GroupKind, str]:
        s = f.summary
        if s is None:
            return "unsummarised", GroupKind.unsummarised, "还没整理"
        d = s.deadline_date
        if s.action_needed and not f.low and d and today <= d <= today + timedelta(SOON_DAYS):
            return "due_soon", GroupKind.due_soon, "马上要做（7 天内截止）"
        if d and d < today:
            return "overdue", GroupKind.overdue, "已过期的提醒（去 Canvas 确认交了没有）"
        if _is_grade(f):
            return "grades", GroupKind.grades, "成绩通知"
        if (course := _course(f, keys)) is not None:
            return f"course:{course}", GroupKind.course, f"课程 {course}"
        if s.action_needed and not f.low:
            return "needs_action", GroupKind.needs_action, "要处理"
        if f.low and f.domain in big:
            return f"sender:{f.domain}", GroupKind.sender, f"{f.domain} 的推送"
        if f.low:
            return "low_value", GroupKind.low_value, "广告和推荐"
        return "other", GroupKind.other, "其他"

    buckets: dict[str, tuple[GroupKind, str, list[MailFacts]]] = {}
    for f in sorted(facts, key=_newest, reverse=True):
        key, kind, label = pick(f)
        buckets.setdefault(key, (kind, label, []))[2].append(f)

    groups: list[TriageGroup] = []
    for key, (kind, label, members) in buckets.items():
        rule = _rule_for(key, kind)
        groups.append(
            TriageGroup(
                key=key,
                kind=kind,
                label=label,
                count=len(members),
                item_ids=[m.item_id for m in members],
                rule=rule,
                rule_description=describe(rule) if rule else "",
            )
        )
    order = list(GroupKind)
    groups.sort(key=lambda g: (order.index(g.kind), -g.count))
    return groups


def _rule_for(key: str, kind: GroupKind) -> Selector | None:
    """Only sender and low-value groups offer 「以后也这样」: deadlines change, senders do not."""
    if kind is GroupKind.sender:
        domain = key.split(":", 1)[1]
        return Selector(
            all_of=[
                TextCondition(field="sender_domain", op="equals", value=domain),
                FlagCondition(flag="low_value"),
            ]
        )
    if kind is GroupKind.low_value:
        return Selector(all_of=[FlagCondition(flag="low_value")])
    return None


_newest: Callable[[MailFacts], float] = lambda f: f.received.timestamp() if f.received else 0.0  # noqa: E731
