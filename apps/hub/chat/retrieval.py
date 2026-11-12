"""Which stored mails a question is about, without embeddings or new dependencies (T-0030).

Tokens are ASCII words and CJK character pairs (Chinese has no spaces), scored by IDF so
words found in every mail ("邮件", "通知") count little. The newest mails and mails with a
deadline soon are always included, so "这周有哪些作业要交" works without a keyword match.
"""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from packages.contracts.summaries import EmailSummary

_ASCII = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
FOLLOW_UP_WEIGHT = 0.5  # tokens from the previous question still count, at half weight


@dataclass(frozen=True)
class Candidate:
    item_id: str
    received: datetime | None
    sender: str
    subject: str
    summary: EmailSummary

    def text(self) -> str:
        s = self.summary
        return " ".join([self.subject, self.sender, s.gist, *s.points, s.action, s.deadline_text])


def tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKC", text).lower()
    out = {w for w in _ASCII.findall(norm) if len(w) >= 2}
    # Character pairs only: a lone CJK character ("交") could never match mail text, whose
    # longer runs yield only pairs, and single characters would match almost everything.
    for run in _CJK.findall(norm):
        out.update(run[i : i + 2] for i in range(len(run) - 1))
    return out


_NEVER = datetime.min.replace(tzinfo=UTC)


def _when(dt: datetime | None) -> datetime:
    return dt or _NEVER  # times come from UTCDateTime columns: always aware


def select(
    question: str,
    last_user_turn: str,
    pool: list[Candidate],
    today: date,
    *,
    recent: int = 20,
    upcoming: int = 10,
    cap: int = 60,
) -> list[Candidate]:
    """At most `cap` candidates, newest first: the `recent` newest, up to `upcoming` with a
    deadline from yesterday to two weeks ahead, then the best keyword matches."""
    if not pool:
        return []
    texts = {c.item_id: tokens(c.text()) for c in pool}
    df: Counter[str] = Counter()
    for toks in texts.values():
        df.update(toks)
    n = len(pool)
    weights: dict[str, float] = {}
    for t in tokens(last_user_turn):
        weights[t] = FOLLOW_UP_WEIGHT
    for t in tokens(question):
        weights[t] = 1.0

    def score(c: Candidate) -> float:
        return sum(w * math.log(1 + n / df[t]) for t, w in weights.items() if t in texts[c.item_id])

    newest = sorted(pool, key=lambda c: _when(c.received), reverse=True)
    soon_from, soon_to = today - timedelta(days=1), today + timedelta(days=14)
    soon = sorted(
        (
            c
            for c in pool
            if c.summary.deadline_date and soon_from <= c.summary.deadline_date <= soon_to
        ),
        key=lambda c: c.summary.deadline_date or today,
    )
    scored = [(score(c), c) for c in newest]
    matches = [c for s, c in sorted(scored, key=lambda sc: -sc[0]) if s > 0]  # stable: newest

    picked: dict[str, Candidate] = {}
    for group, limit in ((newest, recent), (soon, upcoming), (matches, cap)):
        added = 0
        for c in group:
            if len(picked) >= cap or added >= limit:
                break
            if c.item_id not in picked:
                picked[c.item_id] = c
                added += 1
    return sorted(picked.values(), key=lambda c: _when(c.received), reverse=True)
