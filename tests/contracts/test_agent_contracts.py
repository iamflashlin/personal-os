import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.hub.audit.service import redact_text
from packages.contracts.actions import (
    ACTION_SPECS,
    AUTO_APPROVED_RISKS,
    ActionName,
    ActionRequest,
    ActionResult,
    ActionRunStatus,
    ActionStatus,
    OpenFolderParams,
    OpenUrlParams,
    RiskLevel,
    parse_params,
)
from packages.contracts.agent_protocol import (
    AGENT_TO_HUB,
    HUB_TO_AGENT,
    ActionRequestMsg,
    ActionResultMsg,
    CloseCode,
    Heartbeat,
    HeartbeatAck,
    Hello,
    Welcome,
)
from packages.contracts.devices import PAIRING_CODE_PATTERN, TOKEN_PREFIX, PairRequest

ULID = "01JC0000000000000000000000"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def test_every_action_is_whitelisted_reversible_and_auto_approved_in_s2() -> None:
    assert set(ACTION_SPECS) == set(ActionName)
    for name, spec in ACTION_SPECS.items():
        assert spec.name == name
        assert spec.risk in AUTO_APPROVED_RISKS
        assert spec.reversible
        assert 0 < spec.timeout_s <= 120
    assert {RiskLevel.P0, RiskLevel.P1} == AUTO_APPROVED_RISKS


def test_every_agent_status_is_a_stored_run_status() -> None:
    assert {s.value for s in ActionStatus} <= {s.value for s in ActionRunStatus}


@pytest.mark.parametrize("url", ["http://127.0.0.1:9/x", "https://example.com/a?b=c"])
def test_open_url_accepts_http_and_https(url: str) -> None:
    assert OpenUrlParams(url=url, expect_title_contains="t").url.scheme in ("http", "https")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    ["file:///C:/Windows/System32", "javascript:alert(1)", "ms-settings:privacy", "ftp://x/y"],
)
def test_open_url_refuses_every_other_scheme(url: str) -> None:
    with pytest.raises(ValidationError):
        parse_params(ActionName.open_url, {"url": url, "expect_title_contains": "t"})


@pytest.mark.parametrize("path", ["D:\\dev\\notes", "C:/Users/me/proj", "/home/me/proj"])
def test_open_folder_accepts_absolute_paths(path: str) -> None:
    assert OpenFolderParams(path=path).path == path


@pytest.mark.parametrize(
    "path",
    [
        "notes",
        "..\\x",
        "D:\\a & calc",
        "D:\\a|b",
        'D:\\a" --x',
        "D:\\%PATH%",
        "D:\\a\nb",
        "\\\\attacker.example\\share",
        "//attacker.example/share",
        "\\\\?\\C:\\x",
    ],
)
def test_open_folder_refuses_relative_paths_and_cmd_metacharacters(path: str) -> None:
    with pytest.raises(ValidationError):
        parse_params(ActionName.open_folder_in_editor, {"path": path})


def test_params_refuse_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        parse_params(ActionName.open_folder_in_editor, {"path": "D:\\x", "args": "--y"})


def test_every_message_round_trips_through_its_union() -> None:
    request = ActionRequest(
        action_id=ULID,
        idempotency_key="k",
        name=ActionName.open_url,
        params={"url": "https://example.com/"},
        risk_level=RiskLevel.P1,
        timeout_s=20,
        issued_at=NOW,
    )
    result = ActionResult(
        action_id=ULID,
        idempotency_key="k",
        status=ActionStatus.succeeded,
        started_at=NOW,
        finished_at=NOW,
    )
    to_hub = [
        Hello(agent_version="0.1", platform="windows", supported_actions=[ActionName.open_url]),
        Heartbeat(),
        ActionResultMsg(result=result),
    ]
    to_agent = [
        Welcome(device_id=ULID, heartbeat_interval_s=15),
        HeartbeatAck(),
        ActionRequestMsg(request=request),
    ]
    for message in to_hub:
        assert AGENT_TO_HUB.validate_json(message.model_dump_json()) == message
    for message in to_agent:
        assert HUB_TO_AGENT.validate_json(message.model_dump_json()) == message


@pytest.mark.parametrize(
    "frame",
    [
        '{"type": "welcome", "device_id": "x", "heartbeat_interval_s": 1}',  # wrong direction
        '{"type": "heartbeat", "v": 2}',
        '{"type": "heartbeat", "extra": 1}',
        '{"type": "nope"}',
    ],
)
def test_the_hub_refuses_frames_outside_protocol_v1(frame: str) -> None:
    with pytest.raises(ValidationError):
        AGENT_TO_HUB.validate_json(frame)


def test_close_codes_match_adr_0014() -> None:
    assert {c.name: int(c) for c in CloseCode} == {
        "protocol_error": 1008,
        "unauthorized": 4401,
        "heartbeat_timeout": 4408,
        "replaced": 4409,
    }


def test_pairing_codes_use_crockford_base32() -> None:
    assert re.fullmatch(PAIRING_CODE_PATTERN, "7K3M-9QXZ")
    assert re.fullmatch(PAIRING_CODE_PATTERN, "7K3M9QXZ")
    for bad in ("7K3M-9QXI", "7K3M-9QXL", "7K3M-9QXO", "7K3M-9QXU", "7K3-9QXZ"):
        assert not re.fullmatch(PAIRING_CODE_PATTERN, bad)
    assert PairRequest(code=" 7k3m-9qxz ", device_name="pc", platform="windows").code == (
        "7K3M-9QXZ"
    )


def test_agent_tokens_are_recognised_by_redaction() -> None:
    token = TOKEN_PREFIX + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v"
    assert redact_text(f"agent said {token} end") == "agent said [REDACTED] end"
