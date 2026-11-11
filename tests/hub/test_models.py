# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from apps.hub.audit.models import AuditEventRow
from apps.hub.core.db import make_engine, upgrade_to_head
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.models import pricing, service
from apps.hub.models.deepseek import DeepSeekProvider, check_base_url
from apps.hub.models.fake import FakeProvider
from apps.hub.models.models import ModelCallRow
from apps.hub.models.prompts import Prompt, load_prompt
from apps.hub.models.provider import ModelProvider, ProviderErrorKind, Usage
from tests.hub.fake_openai import FakeOpenAI, Reply

KEY = "sk-test-0123456789abcdef0123456789abcdef"
OWNER = Actor(owner_id="local", source="test")
OTHER = Actor(owner_id="other", source="test")
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
PROMPT = Prompt("demo", 1, "Reply in json.", "Subject: $subject\n$body", "a" * 64)
MODEL = "deepseek-flash"
BIG = 10_000_000  # US$10 in micro-USD


class Answer(BaseModel):
    answer: str


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    tmp_path.mkdir(exist_ok=True)
    e = make_engine(tmp_path)
    upgrade_to_head(e)
    yield e
    e.dispose()


@pytest.fixture
def store(engine: Engine) -> credentials.MemorySecretStore:
    s = credentials.MemorySecretStore()
    with Session(engine) as session:
        credentials.put(session, OWNER, s, service.CREDENTIAL, KEY, "")
    return s


@pytest.fixture
def stub() -> Iterator[FakeOpenAI]:
    with FakeOpenAI() as s:
        yield s


def client(
    engine: Engine,
    store: credentials.SecretStore,
    provider: ModelProvider,
    budget: int = BIG,
    model: str = MODEL,
    now: datetime = NOW,
) -> service.ModelClient:
    return service.open_client(
        engine,
        OWNER,
        store,
        provider,
        model,
        budget,
        clock=lambda: now,
    )


def call(c: service.ModelClient, subject: str = "hi", body: str = "hello") -> tuple[Answer, str]:
    return c.call_json(
        PROMPT,
        {"subject": subject, "body": body},
        Answer,
        purpose="test",
        ref="item-1",
        max_output_tokens=200,
    )


def rows(engine: Engine) -> list[ModelCallRow]:
    with Session(engine) as session:
        return list(session.scalars(select(ModelCallRow).order_by(ModelCallRow.created_at)))


def test_adapter_sends_json_mode_and_reads_usage(engine, store, stub) -> None:
    stub.replies.append(Reply(prefix=b"\n\n  \n"))  # keep-alive blank lines first
    answer, call_id = call(client(engine, store, DeepSeekProvider(stub.url)))

    assert answer.answer == "ok"
    sent = stub.requests[0]
    assert sent["model"] == MODEL
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_tokens"] == 200
    assert sent["stream"] is False
    assert sent["messages"][1]["content"] == "Subject: hi\nhello"
    assert stub.headers[0]["Authorization"] == f"Bearer {KEY}"

    [row] = rows(engine)
    assert row.id == call_id
    assert (row.status, row.vendor, row.model, row.purpose, row.ref) == (
        "ok",
        "deepseek",
        MODEL,
        "test",
        "item-1",
    )
    assert (row.prompt_name, row.prompt_version, row.prompt_sha) == ("demo", 1, "a" * 64)
    assert (row.input_tokens, row.cached_input_tokens, row.output_tokens) == (120, 20, 30)
    # 100 miss x 0.30 + 20 hit x 0.006 + 30 out x 1.20 = 30 + 0.12 + 36 = 66.12 -> 67
    assert row.cost_micro_usd == 67
    assert row.estimate_micro_usd >= row.cost_micro_usd
    assert row.request_id == "req-123"
    assert row.finish_reason == "stop"


@pytest.mark.parametrize(
    ("status", "reason"),
    [(401, "key_rejected"), (402, "no_balance"), (429, "rate_limited")],
)
def test_account_errors_make_the_model_unavailable(engine, store, stub, status, reason) -> None:
    stub.replies.append(Reply(status=status))
    with pytest.raises(service.ModelUnavailable) as caught:
        call(client(engine, store, DeepSeekProvider(stub.url)))
    assert caught.value.reason == reason
    [row] = rows(engine)
    assert (row.status, row.cost_micro_usd) == ("error", 0)
    with Session(engine) as session:
        assert service.last_error(session, OWNER) == reason


def test_server_error_is_retryable_and_free(engine, store, stub) -> None:
    stub.replies.append(Reply(status=500))
    with pytest.raises(service.ModelFailed) as caught:
        call(client(engine, store, DeepSeekProvider(stub.url)))
    assert caught.value.retryable
    assert caught.value.kind == ProviderErrorKind.transient
    assert rows(engine)[0].cost_micro_usd == 0


def test_timeout_is_retryable_and_counts_the_estimate(engine, store, stub) -> None:
    stub.replies.append(Reply(delay_s=1.0))
    slow = DeepSeekProvider(stub.url, timeout_s=0.2)
    with pytest.raises(service.ModelFailed) as caught:
        call(client(engine, store, slow))
    assert caught.value.retryable
    [row] = rows(engine)
    assert row.status == "error"
    assert row.cost_micro_usd == row.estimate_micro_usd > 0  # it may have been billed


@pytest.mark.parametrize(
    "reply",
    [
        Reply(content=""),
        Reply(content="not json at all"),
        Reply(content='{"wrong": "shape"}'),
        Reply(raw=b"<html>gateway</html>"),
    ],
)
def test_bad_output_is_retryable(engine, store, stub, reply) -> None:
    stub.replies.append(reply)
    with pytest.raises(service.ModelFailed) as caught:
        call(client(engine, store, DeepSeekProvider(stub.url)))
    assert caught.value.retryable
    assert caught.value.kind == ProviderErrorKind.bad_output
    [row] = rows(engine)
    assert row.error_kind == "bad_output"
    if reply.raw is None:  # the vendor answered and reported usage: that is billed
        assert row.output_tokens == 30
        assert row.cost_micro_usd == 67


@pytest.mark.parametrize(
    "body",
    [
        "plain ascii text " * 200,
        "中文邮件正文，包含截止日期和作业要求。" * 120,
        "mixed 混合 🙂 " * 300,
    ],
)
def test_estimate_is_an_upper_bound(engine, store, stub, body) -> None:
    # A byte-level tokenizer never makes more tokens than bytes; pretend the worst case.
    user = PROMPT.render({"subject": "s", "body": body})
    worst_input = len((PROMPT.system + user).encode("utf-8"))
    estimate = service.estimate_micro_usd("deepseek", MODEL, PROMPT.system, user, 200)
    worst = service.cost_micro_usd("deepseek", MODEL, Usage(worst_input, 0, 200))
    assert estimate >= worst


def test_budget_refuses_before_any_request(engine, store, stub) -> None:
    c = client(engine, store, DeepSeekProvider(stub.url), budget=10)  # 10 micro-USD
    with pytest.raises(service.ModelUnavailable) as caught:
        call(c)
    assert caught.value.reason == "budget"
    assert stub.requests == []
    assert rows(engine) == []


def test_spend_counts_this_utc_month_including_reserved_and_maybe_billed(engine, store) -> None:
    def add(created: datetime, cost: int, status: str = "ok", owner: str = "local") -> None:
        with Session(engine) as session:
            session.add(
                ModelCallRow(
                    owner_id=owner,
                    source="test",
                    version=1,
                    created_at=created,
                    updated_at=created,
                    vendor="deepseek",
                    model=MODEL,
                    purpose="t",
                    prompt_name="p",
                    prompt_version=1,
                    prompt_sha="x",
                    status=status,
                    cost_micro_usd=cost,
                    estimate_micro_usd=cost,
                )
            )
            session.commit()

    add(datetime(2026, 10, 31, 23, 59, tzinfo=UTC), 1000)  # last month
    add(datetime(2026, 11, 1, 0, 0, tzinfo=UTC), 5)
    add(datetime(2026, 11, 5, tzinfo=UTC), 7, status="reserved")
    add(datetime(2026, 11, 6, tzinfo=UTC), 11, status="error")
    add(datetime(2026, 11, 7, tzinfo=UTC), 500, owner="other")
    with Session(engine) as session:
        assert service.month_spent_micro_usd(session, OWNER, NOW) == 23
        assert service.month_spent_micro_usd(session, OTHER, NOW) == 500
        dec = datetime(2026, 12, 1, tzinfo=UTC)
        assert service.month_spent_micro_usd(session, OWNER, dec) == 0
        u = service.usage(session, OWNER, NOW, BIG, "deepseek", MODEL)
        assert (u.month, u.spent_micro_usd, u.calls, u.key_set) == ("2026-11", 23, 3, True)
        assert u.prices_as_of == pricing.AS_OF


def test_no_key_means_no_request(engine, stub) -> None:
    with pytest.raises(service.ModelUnavailable) as caught:
        client(engine, credentials.MemorySecretStore(), DeepSeekProvider(stub.url))
    assert caught.value.reason == "no_key"
    assert stub.requests == []


def test_key_is_revealed_once_per_client(engine, store, stub) -> None:
    c = client(engine, store, DeepSeekProvider(stub.url))
    call(c)
    call(c)
    with Session(engine) as session:
        uses = session.scalars(
            select(AuditEventRow).where(AuditEventRow.action == "credential.use")
        ).all()
    assert len(uses) == 1


def test_unpriced_model_is_refused(engine, store, stub) -> None:
    with pytest.raises(service.ModelUnavailable) as caught:
        client(engine, store, DeepSeekProvider(stub.url), model="some-unpriced-model")
    assert caught.value.reason == "unpriced"


def test_key_and_text_are_never_stored_or_logged(engine, store, stub, caplog, tmp_path) -> None:
    caplog.set_level(logging.DEBUG)
    stub.replies += [Reply(), Reply(status=401), Reply(status=500)]
    c = client(engine, store, DeepSeekProvider(stub.url))
    secret_body = "PRIVATE-MAIL-BODY-42"
    for _ in range(3):
        try:
            call(c, body=secret_body)
        except (service.ModelUnavailable, service.ModelFailed) as exc:
            assert KEY not in str(exc)
    engine.dispose()
    for path in tmp_path.glob("hub.sqlite*"):
        data = path.read_bytes()
        assert KEY.encode() not in data
        assert secret_body.encode() not in data
    assert KEY not in caplog.text
    assert secret_body not in caplog.text


def test_fake_provider_is_deterministic_and_fails_on_markers(engine, store) -> None:
    class Summary(BaseModel):
        gist: str
        action_needed: bool

    fake = FakeProvider()
    c = client(engine, store, fake, model="fake")
    first, _ = c.call_json(
        PROMPT,
        {"subject": "作业", "body": "周五截止"},
        Summary,
        purpose="t",
        ref="r",
        max_output_tokens=100,
    )
    second, _ = c.call_json(
        PROMPT,
        {"subject": "作业", "body": "周五截止"},
        Summary,
        purpose="t",
        ref="r",
        max_output_tokens=100,
    )
    assert first == second
    assert first.action_needed
    assert "作业" in first.gist
    for marker, expected in [
        ("[fake:401]", service.ModelUnavailable),
        ("[fake:500]", service.ModelFailed),
        ("[fake:bad-json]", service.ModelFailed),
    ]:
        with pytest.raises(expected):
            c.call_json(
                PROMPT,
                {"subject": marker, "body": ""},
                Summary,
                purpose="t",
                ref="r",
                max_output_tokens=100,
            )


def test_prompts_load_with_version_and_hash(tmp_path) -> None:
    (tmp_path / "demo.v2.toml").write_text(
        'system = "Answer in json."\nuser = "Mail: $body"\n', encoding="utf-8"
    )
    prompt = load_prompt("demo", 2, root=tmp_path)
    assert (prompt.name, prompt.version, len(prompt.sha256)) == ("demo", 2, 64)
    assert prompt.render({"body": "$subject {x}"}) == "Mail: $subject {x}"  # verbatim
    (tmp_path / "bad.v1.toml").write_text('system = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="user"):
        load_prompt("bad", 1, root=tmp_path)


def test_base_url_must_be_https_or_loopback() -> None:
    assert check_base_url("https://api.deepseek.com/") == "https://api.deepseek.com"
    assert check_base_url("http://127.0.0.1:9999") == "http://127.0.0.1:9999"
    with pytest.raises(ValueError):
        check_base_url("http://api.deepseek.com")


def test_provider_from_settings_and_budget(tmp_path) -> None:
    fake = Settings(data_dir=tmp_path, model_provider="fake")
    assert service.provider_from_settings(fake).vendor == "fake"
    assert service.provider_from_settings(Settings(data_dir=tmp_path)).vendor == "deepseek"
    assert service.budget_micro_usd(Settings(data_dir=tmp_path)) == 10_000_000


def test_usage_json_roundtrip(engine, store) -> None:
    with Session(engine) as session:
        u = service.usage(session, OWNER, NOW, BIG, "deepseek", MODEL)
    assert json.loads(u.model_dump_json())["budget_micro_usd"] == BIG


def test_redirects_are_never_followed_so_the_key_stays_put(engine, store, stub) -> None:
    with FakeOpenAI() as elsewhere:
        stub.replies.append(Reply(status=302, headers={"Location": f"{elsewhere.url}/steal"}))
        with pytest.raises(service.ModelFailed) as caught:
            call(client(engine, store, DeepSeekProvider(stub.url)))
        assert not caught.value.retryable  # 3xx -> bad_request
        assert elsewhere.requests == []
        assert elsewhere.headers == []
    assert rows(engine)[0].cost_micro_usd == 0


def test_missing_usage_is_charged_at_the_estimate(engine, store, stub) -> None:
    stub.replies.append(Reply(usage=None))
    call(client(engine, store, DeepSeekProvider(stub.url)))
    [row] = rows(engine)
    assert row.status == "ok"
    assert row.cost_micro_usd == row.estimate_micro_usd > 0


def test_cost_above_the_estimate_is_flagged(engine, store, stub, caplog) -> None:
    stub.replies.append(
        Reply(
            usage={"prompt_tokens": 10, "prompt_cache_miss_tokens": 10, "completion_tokens": 9999}
        )
    )
    call(client(engine, store, DeepSeekProvider(stub.url)))
    [row] = rows(engine)
    assert row.cost_micro_usd > row.estimate_micro_usd
    assert "above its estimate" in caplog.text
    with Session(engine) as session:
        event = session.scalars(
            select(AuditEventRow).where(AuditEventRow.action == "model_call.call")
        ).one()
    assert event.detail["over_estimate"] is True


def test_key_is_not_in_the_client_repr(engine, store, stub) -> None:
    c = client(engine, store, DeepSeekProvider(stub.url))
    assert KEY not in repr(c)
    assert KEY not in str(c)


def test_unexpected_adapter_errors_settle_the_row_and_do_not_leak(engine, store) -> None:
    class Broken:
        vendor = "fake"

        def complete_json(self, request: object, api_key: str) -> object:
            raise RuntimeError(f"boom with {api_key}")

    with pytest.raises(service.ModelFailed) as caught:
        call(client(engine, store, Broken(), model="fake"))  # type: ignore[arg-type]
    assert caught.value.retryable
    assert KEY not in str(caught.value)
    [row] = rows(engine)
    assert row.status == "error"
    assert row.cost_micro_usd == row.estimate_micro_usd
    assert KEY not in row.error


def test_reservations_share_the_budget(engine, store, stub) -> None:
    # Two clients (as two job runs would be) cannot both spend the last of the budget.
    estimate = service.estimate_micro_usd(
        "deepseek", MODEL, PROMPT.system, PROMPT.render({"subject": "hi", "body": "hello"}), 200
    )
    budget = estimate + estimate // 2
    first = client(engine, store, DeepSeekProvider(stub.url), budget=budget)
    second = client(engine, store, DeepSeekProvider(stub.url), budget=budget)
    stub.replies.append(Reply(delay_s=0.3, usage=None))  # charged at the estimate
    import threading

    errors: list[str] = []

    def run(c: service.ModelClient) -> None:
        try:
            call(c)
        except service.ModelUnavailable as exc:
            errors.append(exc.reason)

    threads = [threading.Thread(target=run, args=(c,)) for c in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == ["budget"]
    assert len(stub.requests) == 1


def test_a_slow_drip_response_hits_the_total_deadline(engine, store, stub) -> None:
    stub.replies.append(Reply(delay_s=0.5))
    slow = DeepSeekProvider(stub.url, timeout_s=5, deadline_s=0.0)
    with pytest.raises(service.ModelFailed):
        call(client(engine, store, slow))


def test_schema_failure_without_usage_is_charged_at_the_estimate(engine, store, stub) -> None:
    stub.replies.append(Reply(content='{"wrong": 1}', usage=None))
    with pytest.raises(service.ModelFailed):
        call(client(engine, store, DeepSeekProvider(stub.url)))
    [row] = rows(engine)
    assert (row.status, row.error_kind) == ("error", "bad_output")
    assert row.cost_micro_usd == row.estimate_micro_usd > 0
