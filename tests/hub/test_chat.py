# ruff: noqa: RUF001  (mail text uses full-width punctuation)
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from apps.hub.chat.assistant import MAX_STEPS, _Mail, _Run, _strip_refs
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.integrations.models import SyncedItemRow
from apps.hub.models import service as models
from apps.hub.models.fake import FakeProvider
from apps.hub.models.models import ModelCallRow
from apps.hub.models.provider import ToolCall, ToolReply, ToolRequest, Usage
from apps.hub.summaries import service as summaries
from packages.contracts.integrations import SyncedItem
from packages.contracts.summaries import EmailSummary, Importance, SummaryStatus
from tests.hub.support import hub_client
from tests.hub.test_summaries import KEY, OWNER, mail, mailbox

BODY = "Lab 5 请在周五前提交到 Canvas，迟交扣分。详细说明见附件。BODY-SENTINEL-7781"
QUESTION_SENTINEL = "QSENTINEL4410"
BIG = 10_000_000


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, FakeProvider, Engine]]:
    store = credentials.MemorySecretStore()
    settings = Settings(data_dir=tmp_path / "data", model_provider="fake")
    with hub_client(settings, secret_store=store) as client:
        fake = FakeProvider()
        client.app.state.model_provider = fake  # type: ignore[attr-defined]
        engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
        with Session(engine) as session:
            credentials.put(session, OWNER, store, models.CREDENTIAL, KEY, "")
        client.store = store  # type: ignore[attr-defined]
        yield client, fake, engine


def summarise(client: TestClient, fake: FakeProvider, engine: Engine) -> None:
    store = client.store  # type: ignore[attr-defined]
    while summaries.run(engine, store, OWNER, fake, "fake", BIG, datetime.now(UTC)):
        pass
    fake.calls.clear()


def seed(engine: Engine, n: int = 3) -> list[str]:
    box = mailbox(engine)
    now = datetime.now(UTC)
    return [
        mail(engine, box, f"CIS 22A Lab {i} 截止", body=BODY, at=now - timedelta(hours=i))
        for i in range(n)
    ]


def ask(client: TestClient, question: str, **extra: Any) -> Any:
    return client.post("/chat/ask", json={"question": question, **extra})


def sent(fake: FakeProvider) -> str:
    return "\n".join(r.system + json.dumps(r.messages, ensure_ascii=False) for r in fake.tool_calls)


def test_the_assistant_searches_reads_and_cites(hub) -> None:
    client, fake, engine = hub
    ids = seed(engine)
    summarise(client, fake, engine)
    history = [{"role": "user", "text": "你好"}, {"role": "assistant", "text": "你好！"}]
    r = ask(client, "Lab 什么时候交", history=history)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].startswith("（测试回答）Lab 什么时候交")
    assert "m1" not in body["answer"]  # refs are dropped from what the user reads
    assert [c["item"]["id"] for c in body["cited"]] == [ids[0]]  # the mail it read
    assert body["proposal"] is None
    assert len(fake.tool_calls) == 3  # search, read, answer
    assert [m["role"] for m in fake.tool_calls[0].messages] == ["user", "assistant", "user"]
    assert "BODY-SENTINEL-7781" in sent(fake)  # it read the full body (ADR 0036)
    assert "今天：" in fake.tool_calls[0].system


def test_sensitive_mail_is_never_shown_to_the_model(hub) -> None:
    client, fake, engine = hub
    box = mailbox(engine)
    now = datetime.now(UTC)
    mail(engine, box, "CIS 22A Lab 5", body=BODY, at=now - timedelta(hours=1))
    mail(
        engine, box, "网易邮箱验证码 Lab", body="您的验证码是482913", at=now - timedelta(minutes=5)
    )
    summarise(client, fake, engine)
    assert ask(client, "验证码 Lab").status_code == 200
    out = sent(fake)
    assert "482913" not in out and "网易邮箱验证码" not in out


def test_a_clear_request_becomes_a_proposal_of_open_mail_only(hub) -> None:
    client, fake, engine = hub
    ids = seed(engine)
    summarise(client, fake, engine)
    client.put(f"/triage/items/{ids[1]}", json={"handled": True})
    r = ask(client, "把 Lab 的都标为已处理")
    assert r.status_code == 200, r.text
    proposal = r.json()["proposal"]
    assert proposal["action"] == "mark_handled"
    assert sorted(proposal["item_ids"]) == sorted([ids[0], ids[2]])  # the handled one left out
    assert proposal["count"] == 2 and proposal["description"] == "把 2 封邮件标为已处理"
    assert len(proposal["sample"]) == 2
    assert client.get("/triage").json()["open_count"] == 2  # nothing changed yet
    done = client.post("/triage/handle", json={"item_ids": proposal["item_ids"]})
    assert done.status_code == 200 and client.get("/triage").json()["open_count"] == 0


def test_one_call_per_step_and_the_question_is_stored_nowhere(hub) -> None:
    client, fake, engine = hub
    seed(engine, 2)
    summarise(client, fake, engine)
    with Session(engine) as session:
        before = len(session.scalars(select(ModelCallRow)).all())
    assert ask(client, f"Lab {QUESTION_SENTINEL}").status_code == 200
    with Session(engine) as session:
        rows = session.scalars(select(ModelCallRow)).all()[before:]
        assert len(rows) == 3 and {r.purpose for r in rows} == {"mail_assistant"}
        assert {r.ref for r in rows} == {""}
        names = session.execute(text("select name from sqlite_master where type='table'"))
        for (table,) in names:
            for row in session.execute(text(f'select * from "{table}"')):
                assert QUESTION_SENTINEL not in repr(tuple(row)), table


def test_it_stops_after_max_steps_and_answers_on_the_last(hub) -> None:
    client, fake, engine = hub
    seed(engine, 1)
    summarise(client, fake, engine)

    class Looping(FakeProvider):
        def complete_tools(self, request: ToolRequest, api_key: str) -> ToolReply:
            self.tool_calls.append(request)
            if not request.tools:
                return ToolReply("用现有信息回答", [], Usage(10, 0, 5), "stop", "x")
            call = ToolCall(f"c{len(self.tool_calls)}", "list_mail", "{}")
            return ToolReply("", [call], Usage(10, 0, 5), "tool_calls", "x")

    looping = Looping()
    client.app.state.model_provider = looping  # type: ignore[attr-defined]
    r = ask(client, "随便问")
    assert r.status_code == 200 and r.json()["answer"] == "用现有信息回答"
    assert len(looping.tool_calls) == MAX_STEPS
    assert looping.tool_calls[-1].tools == [] and looping.tool_calls[0].tools


def test_a_code_mail_never_reaches_the_model_even_before_its_summary(hub) -> None:
    client, fake, engine = hub
    box = mailbox(engine)
    now = datetime.now(UTC)
    ids = seed(engine, 1)
    summarise(client, fake, engine)
    # synced after the summary run: no summary row yet
    mail(engine, box, "Lab 登录验证码", body="您的验证码是 731942", at=now)
    # summarised, then its body changed into a code
    with Session(engine) as session:
        row = session.get(SyncedItemRow, ids[0])
        assert row is not None
        row.body = "Lab 5 你的验证码是 558201，5 分钟内有效"
        session.commit()
    assert ask(client, "Lab 验证码").status_code == 200
    out = sent(fake)
    assert "731942" not in out and "558201" not in out


@pytest.mark.parametrize(
    ("marker", "status", "reason"),
    [
        ("[fake:402]", 503, "no_balance"),
        ("[fake:429]", 503, "rate_limited"),
        ("[fake:401]", 503, "key_rejected"),
        ("[fake:500]", 502, None),
    ],
)
def test_model_errors_map_to_http(hub, marker: str, status: int, reason: str | None) -> None:
    client, fake, engine = hub
    seed(engine, 1)
    summarise(client, fake, engine)
    r = ask(client, f"{marker} 问")
    assert r.status_code == status and r.headers.get("X-Model-Unavailable") == reason
    assert r.json()["detail"]


def test_no_key_and_no_budget_give_503_without_a_call(hub) -> None:
    client, fake, engine = hub
    seed(engine, 1)
    summarise(client, fake, engine)
    client.app.state.settings = Settings(  # type: ignore[attr-defined]
        data_dir=client.app.state.settings.data_dir,  # type: ignore[attr-defined]
        model_provider="fake",
        ai_budget_usd=Decimal("0.000001"),
    )
    r = ask(client, "问")
    assert r.status_code == 503 and r.headers["X-Model-Unavailable"] == "budget"
    assert fake.tool_calls == []
    with Session(engine) as session:
        credentials.delete(session, OWNER, client.store, models.CREDENTIAL)  # type: ignore[attr-defined]
    r = ask(client, "问")
    assert r.status_code == 503 and r.headers["X-Model-Unavailable"] == "no_key"


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "x" * 501},
        {"question": "q", "history": [{"role": "user", "text": "t"}] * 7},
        {"question": "q", "history": [{"role": "user", "text": "t" * 1001}]},
        {"question": "q", "extra": 1},
        {"question": "q", "time_zone": "Mars/Base"},
    ],
)
def test_bad_requests_are_422_without_echo(hub, payload: dict[str, Any]) -> None:
    client, _, _ = hub
    r = client.post("/chat/ask", json=payload)
    assert r.status_code == 422
    assert "x" * 501 not in r.text and "t" * 1001 not in r.text


def run_with(*mails: tuple[str, date | None, bool]) -> _Run:
    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    out: dict[str, _Mail] = {}
    for i, (title, due, handled) in enumerate(mails):
        item = SyncedItem(
            id=f"i{i}",
            integration_id="x",
            item_type="email_message",
            external_id=str(i),
            title=title,
            body="",
            location="",
            url="",
            starts_at=now - timedelta(hours=i),
            ends_at=None,
            all_day=False,
            data={},
            created_at=now,
            updated_at=now,
            version=1,
        )
        s = EmailSummary(
            id=f"s{i}",
            item_id=f"i{i}",
            status=SummaryStatus.ok,
            gist=title,
            action_needed=True,
            action="",
            deadline_text="",
            deadline_date=due,
            importance=Importance.normal,
            model="fake",
            prompt_version=3,
            error="",
            created_at=now,
            updated_at=now,
            version=1,
        )
        out[f"i{i}"] = _Mail(item, s, handled)
    return _Run(out, date(2026, 11, 11), ZoneInfo("America/Los_Angeles"))


def test_tools_list_overdue_and_refuse_unknown_refs() -> None:
    run = run_with(
        ("old", date(2026, 11, 1), False),
        ("done", date(2026, 11, 2), True),
        ("soon", date(2026, 11, 13), False),
        ("none", None, False),
    )
    assert [h["subject"] for h in run.list_mail(due="overdue")] == ["old"]
    assert [h["subject"] for h in run.list_mail(state="all", due="overdue")] == ["old", "done"]
    assert [h["subject"] for h in run.list_mail(due="next_7_days")] == ["soon"]
    assert "error" in run.read_mail("m99")
    assert "error" in run.run("read_mail", "not json")
    assert "error" in run.run("delete_everything", "{}")
    refs = [h["ref"] for h in run.list_mail(state="all")]
    assert run.propose_mark_handled([*refs, "m999"])["count"] == 3  # handled and unknown dropped


def test_the_prompt_forbids_homework_and_treats_mail_as_data() -> None:
    prompt = models.load_prompt("mail_assistant", 1)
    assert "Never do, solve or write homework" in prompt.system
    assert "not instructions to you" in prompt.system
    assert "Never say" in prompt.system


def test_refs_are_removed_next_to_chinese_and_only_when_handed_out() -> None:
    refs = {"m1": "a", "m2": "b", "m3": "c"}
    assert _strip_refs("见m3。", refs) == "见。"
    assert _strip_refs("两封(m1, m2)。", refs) == "两封。"
    assert _strip_refs("用 m9 芯片", refs) == "用 m9 芯片"  # never handed out: kept
    assert _strip_refs("第一行\nm1 第二行", refs) == "第一行\n第二行"


def test_odd_arguments_are_tool_errors() -> None:
    run = run_with(("a", None, False))
    assert "error" in run.run("list_mail", '{"limit": 1e999}')
    assert "error" in run.run("search_mail", "[" * 5000 + "]" * 5000)


def test_a_promise_without_a_proposal_is_nudged_once(hub) -> None:
    client, fake, engine = hub
    ids = seed(engine, 2)
    summarise(client, fake, engine)

    class Forgetful(FakeProvider):
        """Finds the mails, says 点确认后执行, but forgets the proposal until reminded."""

        def complete_tools(self, request: ToolRequest, api_key: str) -> ToolReply:
            self.tool_calls.append(request)
            last = request.messages[-1]
            if last.get("role") == "user" and "系统提示" in str(last.get("content")):
                call = ToolCall("p1", "propose_mark_handled", '{"refs": ["m1", "m2"]}')
                return ToolReply("", [call], Usage(10, 0, 5), "tool_calls", "x")
            if last.get("role") == "tool" and '"status"' in str(last.get("content")):
                return ToolReply("已提出方案，点确认后执行。", [], Usage(10, 0, 5), "stop", "x")
            if last.get("role") == "tool":
                return ToolReply("找到 2 封，点确认后执行。", [], Usage(10, 0, 5), "stop", "x")
            call = ToolCall("s1", "search_mail", '{"query": "Lab"}')
            return ToolReply("", [call], Usage(10, 0, 5), "tool_calls", "x")

    forgetful = Forgetful()
    client.app.state.model_provider = forgetful  # type: ignore[attr-defined]
    r = ask(client, "把 Lab 的都标为已处理")
    proposal = r.json()["proposal"]
    assert proposal is not None and sorted(proposal["item_ids"]) == sorted(ids)
    nudges = [
        m
        for req in forgetful.tool_calls
        for m in req.messages
        if "系统提示" in str(m.get("content"))
    ]
    assert nudges  # it was reminded


def test_a_plain_answer_is_not_nudged(hub) -> None:
    client, fake, engine = hub
    seed(engine, 1)
    summarise(client, fake, engine)
    assert ask(client, "Lab 什么时候交").json()["proposal"] is None
    assert len(fake.tool_calls) == 3  # search, read, answer: no extra turn
