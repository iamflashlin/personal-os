# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""The mail assistant: the model calls tools to search, read and list the user's mail, and
can propose marking mails handled (ADR 0036). Nothing is changed here: a proposal is only
shown to the user, who confirms it with a click (POST /triage/handle).

What the model can see: mail that is not sensitive (sensitive mail - one-time codes, reset
links - is never searched, listed or read), the full body of a mail it reads, and the
conversation. Nothing is stored: model_call rows get ref="".
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.hub.core.domain import Actor
from apps.hub.credentials import service as credentials
from apps.hub.integrations import service as integrations
from apps.hub.models import service as models
from apps.hub.summaries import service as summaries
from apps.hub.triage import service as triage
from packages.contracts.chat import MAX_CITED, ChatAnswer, ChatAsk, ChatProposal, CitedMail
from packages.contracts.integrations import SyncedItem
from packages.contracts.summaries import EmailSummary, SummaryStatus
from packages.contracts.triage import MAX_BATCH

PROMPT_NAME, PROMPT_VERSION = "mail_assistant", 1
PURPOSE = "mail_assistant"
EMAIL = "email_message"
MAX_STEPS = 6  # model turns per question: each is one billed call
MAX_OUTPUT_TOKENS = 900
SEARCH_LIMIT, LIST_LIMIT = 15, 30
BODY_CHARS = 4000
WEEKDAYS = "一二三四五六日"
_ASCII = re.compile(r"[a-z0-9]{2,}")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

TOOLS = [
    models.Tool(
        "search_mail",
        "Full-text search over all of the user's mail (sender, subject, AI title, points, "
        "body). Returns mail heads with refs like m3, best matches first.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    ),
    models.Tool(
        "read_mail",
        "Read one mail in full by its ref: body text, AI points, action, deadline.",
        {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
    ),
    models.Tool(
        "list_mail",
        "List mail newest first. state: open (not handled) or all. due: overdue (deadline "
        "before today), next_7_days, or any.",
        {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["open", "all"]},
                "due": {"type": "string", "enum": ["overdue", "next_7_days", "any"]},
                "limit": {"type": "integer"},
            },
        },
    ),
    models.Tool(
        "propose_mark_handled",
        "Propose marking these mails 已处理 (handled). The user must click 确认; it is not done "
        "until then, so never say it is done.",
        {
            "type": "object",
            "properties": {
                "refs": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
            },
            "required": ["refs"],
        },
    ),
]


def _tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKC", text).lower()
    out = set(_ASCII.findall(norm))
    for run in _CJK.findall(norm):
        out.update(run[i : i + 2] for i in range(len(run) - 1))
    return out


@dataclass
class _Mail:
    item: SyncedItem
    summary: EmailSummary | None  # a fresh `ok` summary, else None
    handled: bool

    @property
    def deadline(self) -> date | None:
        return self.summary.deadline_date if self.summary else None


@dataclass
class _Run:
    """One question's tools: the mail it may see, the refs it has handed out."""

    mails: dict[str, _Mail]
    today: date
    zone: tzinfo
    refs: dict[str, str] = field(default_factory=dict[str, str])  # ref -> item id
    by_id: dict[str, str] = field(default_factory=dict[str, str])  # item id -> ref
    read: list[str] = field(default_factory=list[str])  # item ids read, in order
    proposal: list[str] | None = None

    def ref(self, item_id: str) -> str:
        if item_id not in self.by_id:
            r = f"m{len(self.refs) + 1}"
            self.refs[r], self.by_id[item_id] = item_id, r
        return self.by_id[item_id]

    def head(self, m: _Mail) -> dict[str, Any]:
        s, item = m.summary, m.item
        data = item.data
        when = item.starts_at.astimezone(self.zone) if item.starts_at else None
        return {
            "ref": self.ref(item.id),
            "date": f"{when:%Y-%m-%d %H:%M} 周{WEEKDAYS[when.weekday()]}" if when else "",
            "from": str(data.get("from_name") or data.get("from_address") or ""),
            "subject": item.title[:160],
            "ai_title": s.gist if s else "",
            "deadline": s.deadline_date.isoformat() if s and s.deadline_date else None,
            "handled": m.handled,
        }

    def search_mail(self, query: str = "", limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
        terms = _tokens(query)
        scored: list[tuple[int, float, _Mail]] = []
        for m in self.mails.values():
            s, item = m.summary, m.item
            top = " ".join(
                [
                    str(item.data.get("from_name") or ""),
                    str(item.data.get("from_address") or ""),
                    item.title,
                    s.gist if s else "",
                ]
            )
            rest = " ".join(
                [*(s.points if s else []), s.action if s else "", item.body[:BODY_CHARS]]
            )
            top_t, rest_t = _tokens(top), _tokens(rest)
            score = sum(3 if t in top_t else 1 for t in terms if t in top_t or t in rest_t)
            if score:
                when = item.starts_at.timestamp() if item.starts_at else 0.0
                scored.append((score, when, m))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [self.head(m) for _, _, m in scored[: max(1, min(int(limit), SEARCH_LIMIT))]]

    def read_mail(self, ref: str = "") -> dict[str, Any]:
        m = self.mails.get(self.refs.get(ref, ""))
        if m is None:
            return {"error": "no such ref; use a ref returned by search_mail or list_mail"}
        if m.item.id not in self.read:
            self.read.append(m.item.id)
        s = m.summary
        return {
            **self.head(m),
            "points": s.points if s else [],
            "action": s.action if s else "",
            "body": m.item.body[:BODY_CHARS],
        }

    def list_mail(
        self, state: str = "open", due: str = "any", limit: int = LIST_LIMIT
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        week = self.today + timedelta(days=7)
        ordered = sorted(
            self.mails.values(),
            key=lambda m: m.item.starts_at.timestamp() if m.item.starts_at else 0.0,
            reverse=True,
        )
        for m in ordered:
            if state == "open" and m.handled:
                continue
            d = m.deadline
            if due == "overdue" and not (d and d < self.today):
                continue
            if due == "next_7_days" and not (d and self.today <= d <= week):
                continue
            out.append(self.head(m))
            if len(out) >= max(1, min(int(limit), LIST_LIMIT)):
                break
        return out

    def propose_mark_handled(
        self, refs: list[str] | None = None, reason: str = ""
    ) -> dict[str, Any]:
        ids = [self.refs[r] for r in (refs or []) if r in self.refs]
        open_ids = [i for i in dict.fromkeys(ids) if not self.mails[i].handled][:MAX_BATCH]
        self.proposal = open_ids
        return {"status": "proposed; waiting for the user to click 确认", "count": len(open_ids)}

    def run(self, name: str, arguments: str) -> Any:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
            fn = {
                "search_mail": self.search_mail,
                "read_mail": self.read_mail,
                "list_mail": self.list_mail,
                "propose_mark_handled": self.propose_mark_handled,
            }.get(name)
            if fn is None:
                return {"error": f"unknown tool {name}"}
            return fn(**args)
        except Exception as exc:
            return {"error": f"bad arguments: {type(exc).__name__}"}


def _mails(session: Session, actor: Actor, today: date) -> dict[str, _Mail]:
    heads = integrations.item_heads(session, actor, EMAIL)
    statuses = {
        s.item_id: s
        for s in summaries.summaries_for(session, actor, [h.id for h in heads], limit=None)
    }
    handled = triage.handled_ids(session, actor, today)
    items = integrations.items_by_id(session, actor, [h.id for h in heads])
    out: dict[str, _Mail] = {}
    for h in heads:
        s = statuses.get(h.id)
        item = items.get(h.id)
        if item is None or not item.body.strip():
            continue  # unreadable: nothing to search or read
        if (
            s is not None and s.status is SummaryStatus.skipped_sensitive
        ) or summaries.is_sensitive(item):
            # One-time codes and reset links are never shown to the model, checked on the
            # mail itself too: it may not be summarised yet, or may have changed since.
            continue
        fresh = (
            s
            if s is not None and s.status is SummaryStatus.ok and h.changed <= s.updated_at
            else None
        )
        out[h.id] = _Mail(item, fresh, h.id in handled)
    return out


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
    """One answer; may end with a proposal. Raises ModelUnavailable / ModelFailed."""
    prompt = prompt or models.load_prompt(PROMPT_NAME, PROMPT_VERSION)
    local = now.astimezone(zone)
    with Session(engine) as session:
        mails = _mails(session, actor, local.date())
        unsummarised = summaries.count(session, actor, SummaryStatus.pending)
    run = _Run(mails, local.date(), zone)
    system = (
        prompt.render(
            {
                "today": local.date().isoformat(),
                "weekday": f"周{WEEKDAYS[local.weekday()]}",
                "zone": str(zone),
            }
        )
        + "\n"
        + prompt.system
    )
    messages: list[dict[str, Any]] = [{"role": t.role, "content": t.text} for t in request.history]
    messages.append({"role": "user", "content": request.question})
    client = models.open_client(engine, actor, store, provider, model, budget, lambda: now)
    answer = ""
    for step in range(MAX_STEPS):
        last = step == MAX_STEPS - 1
        reply = client.call_tools(
            models.Prompt(prompt.name, prompt.version, system, "", prompt.sha256),
            messages,
            [] if last else TOOLS,  # the last turn gets no tools: it must answer
            purpose=PURPOSE,
            ref="",
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        if not reply.tool_calls:
            answer = reply.content.strip()
            break
        messages.append(
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in reply.tool_calls
                ],
            }
        )
        for c in reply.tool_calls:
            result = run.run(c.name, c.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:16000],
                }
            )
    else:
        answer = "这个问题我查了几轮还没查完，换个更具体的问法试试？"
    return _answer(run, answer or "在邮件里没找到", unsummarised)


def _answer(run: _Run, text: str, unsummarised: int) -> ChatAnswer:
    """Cited mails: those it read, then those whose ref it wrote; never more than MAX_CITED."""
    named = [run.refs[r] for r in _REF.findall(text) if r in run.refs]
    ids = list(dict.fromkeys([*run.read, *named]))[:MAX_CITED]
    cited = [_cited(run.mails[i]) for i in ids]
    proposal = None
    if run.proposal:
        ids = run.proposal
        proposal = ChatProposal(
            action="mark_handled",
            item_ids=ids,
            count=len(ids),
            description=f"把 {len(ids)} 封邮件标为已处理",  # written by code, not the model
            sample=[_cited(run.mails[i]) for i in ids[:5]],
        )
    clean = _strip_refs(text, run.refs)
    return ChatAnswer(
        answer=clean or text,
        cited=cited,
        considered=len(run.mails),
        unsummarised=unsummarised,
        proposal=proposal,
    )


_REF = re.compile(r"(?<![A-Za-z0-9])m\d+(?![0-9])")
_REF_GROUP = re.compile(r"[（(]\s*m\d+(?:\s*[,，、]\s*m\d+)*\s*[）)]")


def _strip_refs(text: str, refs: dict[str, str]) -> str:
    """Refs mean nothing to the user. Remove those this run handed out, with brackets that
    hold only refs; leave other text (like "m2 芯片") and line breaks alone."""

    def group(m: re.Match[str]) -> str:
        inside = _REF.findall(m.group(0))
        return "" if all(r in refs for r in inside) else m.group(0)

    text = _REF_GROUP.sub(group, text)
    text = _REF.sub(lambda m: "" if m.group(0) in refs else m.group(0), text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"(?m)^[ \t]+", "", text).strip()


def _cited(m: _Mail) -> CitedMail:
    return CitedMail(item=m.item, summary=m.summary)
