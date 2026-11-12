# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Questions about the user's mail, answered from stored summaries (T-0030, ADR 0033).

Stateless: nothing here is stored. The question goes to the model with the sender,
subject, date and summary of at most 60 mails: never a mail body, and never anything from
mail that was not summarised (sensitive, unreadable, pending, failed). `model_call` gets
`ref=""`, so the question text is kept nowhere.
"""

import re
import unicodedata
from datetime import datetime, tzinfo

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.chat.output import ChatOutput
from apps.hub.chat.retrieval import Candidate, select
from apps.hub.core.domain import Actor
from apps.hub.credentials import service as credentials
from apps.hub.integrations import service as integrations
from apps.hub.models import service as models
from apps.hub.summaries import service as summaries
from packages.contracts.chat import MAX_CITED, ChatAnswer, ChatAsk, CitedMail
from packages.contracts.summaries import SummaryBlock, SummaryStatus

PROMPT_NAME, PROMPT_VERSION = "mail_chat", 1
PURPOSE = "mail_chat"
EMAIL = "email_message"
MAX_OUTPUT_TOKENS = 600
MAX_LINE = 400
MAX_HISTORY_TURN = 500
NOTHING = "还没有整理好的邮件可以查。等邮件整理完再来问吧。"
WEEKDAYS = "一二三四五六日"

_TAGS = re.compile(r"<\s*/?\s*(mails|history|question|email)\b[^>]*>", re.IGNORECASE)

# Why the model cannot be used, for the user (shared wording with summaries).
NOTICES = {
    "no_key": summaries.NOTICES[SummaryBlock.no_key],
    "key_rejected": summaries.NOTICES[SummaryBlock.key_rejected],
    "no_balance": summaries.NOTICES[SummaryBlock.no_balance],
    "budget": summaries.NOTICES[SummaryBlock.budget],
    "rate_limited": "DeepSeek 暂时限流，请过一会儿再问",
    "unpriced": "AI 模型配置有误",
}


def defang(text: str) -> str:
    """Mail and user text cannot close a section, open a fake one, or start a new line.
    NFKC first, so full-width brackets count as tags; splitlines knows every line break."""
    tagless = _TAGS.sub("[tag]", unicodedata.normalize("NFKC", text))
    return " ".join(tagless.splitlines()).strip()


def _line(ref: str, c: Candidate, zone: tzinfo) -> str:
    s = c.summary
    when = ""
    if c.received:
        local = c.received.astimezone(zone)  # UTCDateTime columns are aware UTC
        when = f"{local:%m-%d} 周{WEEKDAYS[local.weekday()]}"
    parts = [f"[{ref}] {when}", defang(c.sender), f"主题：{defang(c.subject)}"]
    parts.append(f"标题：{defang(s.gist)}")
    if s.points:
        parts.append("要点：" + "；".join(defang(p) for p in s.points))
    if s.action:
        due = f"（截止 {s.deadline_date.isoformat()}）" if s.deadline_date else ""
        parts.append(f"要做：{defang(s.action)}{due}")
    elif s.deadline_date:
        parts.append(f"截止 {s.deadline_date.isoformat()}")
    if s.low_value or s.importance.value == "low":
        parts.append("次要")
    elif s.importance.value == "high":
        parts.append("重要")
    return " | ".join(parts)[:MAX_LINE]


def _pool(session: Session, actor: Actor) -> list[Candidate]:
    """Fresh `ok` summaries joined to their mail heads; a mail changed after its summary
    is left out (it may have become sensitive since)."""
    heads = {h.id: h for h in integrations.item_heads(session, actor, EMAIL)}
    pool: list[Candidate] = []
    for s in summaries.ok_summaries(session, actor):
        head = heads.get(s.item_id)
        # Changed after its summary (a new body, or only the read state moved): left out
        # until the next summary run checks it, so a mail just read is briefly not found.
        if head is None or head.changed > s.updated_at:
            continue
        pool.append(Candidate(head.id, head.received, head.sender, head.subject, s))
    return pool


def ask(
    engine: Engine,
    store: credentials.SecretStore,
    actor: Actor,
    provider: models.ModelProvider,
    model: str,
    budget: int,
    request: ChatAsk,
    now: datetime,
    zone: tzinfo,
    prompt: models.Prompt | None = None,
) -> ChatAnswer:
    """One answer. Raises `models.ModelUnavailable` / `models.ModelFailed`."""
    prompt = prompt or models.load_prompt(PROMPT_NAME, PROMPT_VERSION)
    local_now = now.astimezone(zone)
    with Session(engine) as session:
        pool = _pool(session, actor)
        unsummarised = summaries.count(session, actor, SummaryStatus.pending)
    last_user = next((t.text for t in reversed(request.history) if t.role == "user"), "")
    chosen = select(request.question, last_user, pool, local_now.date())
    if not chosen:
        return ChatAnswer(answer=NOTHING, cited=[], considered=0, unsummarised=unsummarised)

    refs = {f"m{i}": c for i, c in enumerate(chosen, start=1)}
    history = "\n".join(
        f"{'用户' if t.role == 'user' else '助手'}：{defang(t.text)[:MAX_HISTORY_TURN]}"
        for t in request.history
    )
    variables = {
        "today": local_now.date().isoformat(),
        "weekday": f"周{WEEKDAYS[local_now.weekday()]}",
        "zone": str(zone),
        "mails": "\n".join(_line(ref, c, zone) for ref, c in refs.items()),
        "history": history or "（无）",
        "question": defang(request.question),
    }
    # No transaction is open across the call: it writes `model_call` itself.
    client = models.open_client(engine, actor, store, provider, model, budget, lambda: now)
    out, _ = client.call_json(
        prompt, variables, ChatOutput, purpose=PURPOSE, ref="", max_output_tokens=MAX_OUTPUT_TOKENS
    )

    cited_ids: list[str] = []
    for ref in out.cited:
        c = refs.get(ref)
        if c is not None and c.item_id not in cited_ids:
            cited_ids.append(c.item_id)
    cited_ids = cited_ids[:MAX_CITED]
    by_id = {c.item_id: c for c in chosen}
    with Session(engine) as session:
        items = integrations.items_by_id(session, actor, cited_ids)
    cited = [CitedMail(item=items[i], summary=by_id[i].summary) for i in cited_ids if i in items]
    answer = out.answer.strip() or "在已整理的邮件里没找到"
    return ChatAnswer(answer=answer, cited=cited, considered=len(chosen), unsummarised=unsummarised)


__all__ = ["NOTICES", "ask", "defang"]
