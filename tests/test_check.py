import sys

from tools.check import Step, build_steps, run_step


def test_skipped_step_reports_reason_without_running() -> None:
    result = run_step(Step("noop", ["definitely-not-a-real-binary"], skip_reason="later"))
    assert result.status == "skip"
    assert result.detail == "later"


def test_failing_command_is_reported_as_fail() -> None:
    result = run_step(Step("fails", [sys.executable, "-c", "raise SystemExit(3)"]))
    assert result.status == "fail"
    assert result.detail == "exit 3"


def test_missing_binary_is_a_failure_not_a_crash() -> None:
    result = run_step(Step("missing", ["definitely-not-a-real-binary-xyz"]))
    assert result.status == "fail"
    assert result.detail.startswith("cannot run:")


def test_hung_command_times_out_as_failure() -> None:
    step = Step("hang", [sys.executable, "-c", "import time; time.sleep(30)"])
    result = run_step(step, timeout=0.5)
    assert result.status == "fail"
    assert result.detail.startswith("timeout")


def test_preset_fail_reason_short_circuits() -> None:
    result = run_step(Step("pnpm-less", ["pnpm"], fail_reason="pnpm not found"))
    assert result.status == "fail"
    assert result.detail == "pnpm not found"


def test_gate_covers_python_and_frontend() -> None:
    names = {s.name for s in build_steps()}
    assert {"ruff lint", "pyright", "pytest", "tsc", "vitest"} <= names
