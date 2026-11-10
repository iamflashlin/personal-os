"""Single quality gate. Local and CI run the same command:

    uv run python -m tools.check

Steps run in order; every step runs even if an earlier one fails (a missing tool or
a hung command is reported as that step's failure), so one invocation shows every
problem. Exit code is 0 only if all steps pass.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEP_TIMEOUT_S = 600


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]
    skip_reason: str | None = None
    fail_reason: str | None = None


@dataclass(frozen=True)
class Result:
    name: str
    status: str  # "pass" | "fail" | "skip"
    seconds: float
    detail: str = ""


def build_steps() -> list[Step]:
    py = sys.executable
    pnpm = shutil.which("pnpm")
    no_pnpm = None if pnpm else "pnpm not found on PATH; see docs/SETUP.md"
    pn = pnpm or "pnpm"
    lint_imports = shutil.which("lint-imports", path=str(Path(py).parent))
    no_lint_imports = None if lint_imports else "lint-imports not found next to python; uv sync"
    return [
        Step("ruff lint", [py, "-m", "ruff", "check", "."]),
        Step("ruff format", [py, "-m", "ruff", "format", "--check", "."]),
        Step("pyright", [pn, "exec", "pyright"], fail_reason=no_pnpm),
        Step(
            "module boundaries",
            [lint_imports or "lint-imports", "--no-cache"],
            fail_reason=no_lint_imports,
        ),
        Step("pytest", [py, "-m", "pytest"]),
        Step("tsc", [pn, "run", "typecheck"], fail_reason=no_pnpm),
        Step("vitest", [pn, "run", "test"], fail_reason=no_pnpm),
    ]


def run_step(step: Step, timeout: float = STEP_TIMEOUT_S) -> Result:
    if step.skip_reason is not None:
        return Result(step.name, "skip", 0.0, step.skip_reason)
    if step.fail_reason is not None:
        return Result(step.name, "fail", 0.0, step.fail_reason)
    print(f"\n=== {step.name}: {' '.join(step.argv)}", flush=True)
    start = time.perf_counter()
    try:
        completed = subprocess.run(step.argv, cwd=ROOT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Result(step.name, "fail", time.perf_counter() - start, f"timeout {timeout}s")
    except OSError as exc:
        return Result(step.name, "fail", time.perf_counter() - start, f"cannot run: {exc}")
    elapsed = time.perf_counter() - start
    status = "pass" if completed.returncode == 0 else "fail"
    return Result(step.name, status, elapsed, f"exit {completed.returncode}")


def hooks_warning() -> str | None:
    """Local clones must enable .githooks (blocks direct pushes to main)."""
    if os.environ.get("CI"):
        return None
    try:
        out = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return None
    if out != ".githooks":
        return "WARNING: git hooks not enabled; run `git config core.hooksPath .githooks`"
    return None


def main() -> int:
    results = [run_step(step) for step in build_steps()]
    print("\n=== summary")
    for r in results:
        print(f"{r.status.upper():5} {r.name:18} {r.seconds:6.1f}s  {r.detail}")
    warning = hooks_warning()
    if warning:
        print(f"\n{warning}")
    failed = [r.name for r in results if r.status == "fail"]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
