# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Questions and requests about the user's mail (ADR 0033, ADR 0036): the assistant in
`assistant.py` searches and reads mail with tools and may propose an action."""

from apps.hub.chat.assistant import ask
from apps.hub.summaries import service as summaries
from packages.contracts.summaries import SummaryBlock

# Why the model cannot be used, for the user (shared wording with summaries).
NOTICES = {
    "no_key": summaries.NOTICES[SummaryBlock.no_key],
    "key_rejected": summaries.NOTICES[SummaryBlock.key_rejected],
    "no_balance": summaries.NOTICES[SummaryBlock.no_balance],
    "budget": summaries.NOTICES[SummaryBlock.budget],
    "rate_limited": "DeepSeek 暂时限流，请过一会儿再问",
    "unpriced": "AI 模型配置有误",
}

__all__ = ["NOTICES", "ask"]
