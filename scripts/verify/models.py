"""Check the model layer (ADR 0025) on this PC.

    uv run python scripts/verify/models.py           # offline: real migrations + local stub
    uv run python scripts/verify/models.py --live    # one real DeepSeek call (user-approved)

Offline: a fresh SQLite under `data/verify/`, the real migrations, the DeepSeek adapter
against a 127.0.0.1 OpenAI-compatible stub. Checks a successful call and its row; 401,
429, 500 and bad-JSON handling; refusal by the budget before any request; and that the
key is in no byte of `hub.sqlite*` and not in this script's output.

--live: reads the key the user entered on 连接 from Windows Credential Manager
(`personal-os-hub`, `local:deepseek`) without printing it, copies it into a throwaway
store, and makes one call with a fixed tiny prompt and no personal data. Passes when the
reply is valid JSON, usage was parsed, cost <= US$0.001 and the estimate >= the cost.
Exit code 0 only if all checks pass.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.hub.core.db import make_engine, upgrade_to_head  # noqa: E402
from apps.hub.core.domain import Actor  # noqa: E402
from apps.hub.credentials import service as credentials  # noqa: E402
from apps.hub.models import service  # noqa: E402
from apps.hub.models.litellm_adapter import LiteLLMProvider  # noqa: E402
from apps.hub.models.models import ModelCallRow  # noqa: E402
from apps.hub.models.prompts import Prompt  # noqa: E402
from tests.hub.fake_openai import FakeOpenAI, Reply  # noqa: E402

OWNER = Actor(owner_id="local", source="verify")
FAKE_KEY = "sk-verify-6b1f0c2d9e8a7f6b5c4d3e2f1a0b9c8d"
MODEL = "deepseek-flash"
PROMPT = Prompt(
    "verify",
    1,
    "You are a test endpoint. Reply with a json object only.",
    'Reply with exactly this json: {"answer": "$word"}',
    "0" * 64,
)
LIVE_CAP_MICRO_USD = 1000  # US$0.001
USED_KEYS: list[str] = [FAKE_KEY]  # every key this run touched, for the leak checks


class Answer(BaseModel):
    answer: str


class CheckFailed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise CheckFailed(message)


def fresh_dir(label: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = ROOT / "data" / "verify" / f"{label}-{stamp}"
    path.mkdir(parents=True)
    return path


def last_row(engine: object) -> ModelCallRow:
    with Session(engine) as s:  # type: ignore[arg-type]
        row = s.scalars(select(ModelCallRow).order_by(ModelCallRow.created_at.desc())).first()
    assert row is not None
    return row


def ask(client: service.ModelClient, word: str) -> Answer:
    answer, _ = client.call_json(
        PROMPT, {"word": word}, Answer, purpose="verify", ref=word, max_output_tokens=50
    )
    return answer


def offline() -> None:
    data = fresh_dir("models")
    engine = make_engine(data)
    upgrade_to_head(engine)
    store = credentials.MemorySecretStore()
    with Session(engine) as s:
        credentials.put(s, OWNER, store, service.CREDENTIAL, FAKE_KEY, "")
    print(f"data dir: {data}")

    with FakeOpenAI() as stub:
        client = service.open_client(
            engine, OWNER, store, LiteLLMProvider("deepseek", stub.url), MODEL, 10_000_000
        )
        stub.replies.append(Reply(content='{"answer": "ok"}'))
        answer = ask(client, "ok")
        row = last_row(engine)
        check(answer.answer == "ok", "a successful call returns validated output")
        check(
            row.status == "ok" and row.cost_micro_usd > 0 and row.input_tokens == 120,
            f"its model_call row: status={row.status} tokens={row.input_tokens}/"
            f"{row.output_tokens} cost={row.cost_micro_usd} micro-USD "
            f"estimate={row.estimate_micro_usd}",
        )
        check(stub.requests[0]["response_format"] == {"type": "json_object"}, "JSON mode is on")

        for status, reason in [(401, "key_rejected"), (429, "rate_limited")]:
            stub.replies.append(Reply(status=status))
            try:
                ask(client, "x")
                check(False, f"HTTP {status} raises")
            except service.ModelUnavailable as exc:
                check(exc.reason == reason, f"HTTP {status} -> {exc.reason}, cost 0")
        stub.replies.append(Reply(status=500))
        try:
            ask(client, "x")
            check(False, "HTTP 500 raises")
        except service.ModelFailed as exc:
            check(exc.retryable, "HTTP 500 -> retryable failure")
        stub.replies.append(Reply(content="this is not json"))
        try:
            ask(client, "x")
            check(False, "bad JSON raises")
        except service.ModelFailed as exc:
            check(
                exc.retryable and last_row(engine).error_kind == "bad_output",
                "bad JSON -> retryable bad_output, billed tokens recorded",
            )

        before = len(stub.requests)
        tiny = service.open_client(
            engine, OWNER, store, LiteLLMProvider("deepseek", stub.url), MODEL, 1
        )
        try:
            ask(tiny, "x")
            check(False, "budget refusal raises")
        except service.ModelUnavailable as exc:
            check(
                exc.reason == "budget" and len(stub.requests) == before,
                "over the budget: refused before any HTTP request",
            )

    engine.dispose()
    leaked = [p.name for p in data.glob("hub.sqlite*") if FAKE_KEY.encode() in p.read_bytes()]
    check(not leaked, f"key not in any database file ({len(list(data.glob('hub.sqlite*')))} files)")


def live() -> int:
    key = credentials.KeyringSecretStore("personal-os-hub").get(f"local:{service.CREDENTIAL}")
    if not key:
        print("先在连接页输入 DeepSeek key")
        return 1
    USED_KEYS.append(key)
    data = fresh_dir("models-live")
    engine = make_engine(data)
    upgrade_to_head(engine)
    store = credentials.MemorySecretStore()
    with Session(engine) as s:
        credentials.put(s, OWNER, store, service.CREDENTIAL, key, "")
    client = service.open_client(
        engine, OWNER, store, LiteLLMProvider("deepseek"), MODEL, LIVE_CAP_MICRO_USD
    )
    answer = ask(client, "pong")
    row = last_row(engine)
    check(answer.answer == "pong", "DeepSeek returned valid JSON in the asked shape")
    check(
        row.input_tokens > 0 and row.output_tokens > 0,
        f"usage parsed: input={row.input_tokens} (cached {row.cached_input_tokens}) "
        f"output={row.output_tokens} finish={row.finish_reason}",
    )
    check(
        row.cost_micro_usd <= LIVE_CAP_MICRO_USD, f"cost {row.cost_micro_usd} micro-USD <= US$0.001"
    )
    check(
        row.estimate_micro_usd >= row.cost_micro_usd,
        f"estimate {row.estimate_micro_usd} >= actual {row.cost_micro_usd}",
    )
    engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            code = live() if args.live else (offline() or 0)
    except CheckFailed:
        code = 1
    finally:
        out = captured.getvalue()
        sys.stdout.write(out)
    if any(k in out for k in USED_KEYS):
        print("FAIL  a key appeared in this script's output")
        return 1
    print(f"RESULT: {'PASS' if code == 0 else 'FAIL'} (models{' --live' if args.live else ''})")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
