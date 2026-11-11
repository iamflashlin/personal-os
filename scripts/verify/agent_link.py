"""Real-process check of the agent link: a Hub process and an agent process.

    uv run python scripts/verify/agent_link.py [--agent-log-out agent.log]

Pairs a real agent (token in keyring under a unique, throwaway service name), then checks:
online within 15 s, reconnect within 35 s after a Hub restart, exit code 3 within 10 s
after revoke and again on a second start, and that the keyring entry is gone at the end.
No action is sent, so no window is opened. Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import keyring

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.desktop_agent.connection import AgentExit  # noqa: E402
from apps.desktop_agent.token_store import USERNAME  # noqa: E402

HEARTBEAT_S = "1"


class CheckFailed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise CheckFailed(message)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(condition: Callable[[], bool], timeout_s: float) -> float | None:
    """Seconds until `condition` held, or None if it never did."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if condition():
            return time.monotonic() - started
        time.sleep(0.2)
    return None


class Hub:
    def __init__(self, data_dir: Path, port: int, logs: Path) -> None:
        self.env = {
            **os.environ,
            "POS_DATA_DIR": str(data_dir),
            "POS_HUB_PORT": str(port),
            "POS_AGENT_HEARTBEAT_S": HEARTBEAT_S,
        }
        self.env.pop("POS_HUB_HOST", None)
        self.url = f"http://127.0.0.1:{port}"
        self.logs = logs
        self.starts = 0
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.starts += 1
        log = (self.logs / f"hub-{self.starts}.log").open("wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "apps.hub"], cwd=ROOT, env=self.env, stdout=log, stderr=log
        )
        healthy = wait_until(self._healthy, 30)
        check(healthy is not None, f"Hub process #{self.starts} answers /health")

    def _healthy(self) -> bool:
        try:
            return httpx.get(f"{self.url}/health", timeout=2).status_code == 200
        except httpx.TransportError:
            return False

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)

    def get(self, path: str) -> Any:
        return httpx.get(f"{self.url}{path}", timeout=5).json()

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.post(f"{self.url}{path}", timeout=5, **kwargs)


def agent_argv(command: str, *extra: str) -> list[str]:
    return [sys.executable, "-m", "apps.desktop_agent", command, *extra]


def verify(hub: Hub, agent_env: dict[str, str], agent_log: Path) -> str:
    """Runs every check; returns the token so the caller can prove it was never logged."""
    code = hub.post("/devices/pairing-codes").json()["code"]
    paired = subprocess.run(
        agent_argv("pair", "--code", code), cwd=ROOT, env=agent_env, capture_output=True, text=True
    )
    print(f"pair -> exit {paired.returncode}: {paired.stdout.strip()}", flush=True)
    check(paired.returncode == 0, "`apps.desktop_agent pair` exits 0")
    token = keyring.get_password(agent_env["POS_AGENT_KEYRING_SERVICE"], USERNAME)
    check(token is not None and token.startswith("posd_"), "the token is in keyring")
    assert token is not None
    (device,) = hub.get("/devices")

    with agent_log.open("ab") as log:
        agent = subprocess.Popen(agent_argv("run"), cwd=ROOT, env=agent_env, stdout=log, stderr=log)
    try:
        online = wait_until(lambda: hub.get("/agent/status")["online"], 15)
        check(online is not None, f"agent online within 15 s ({online or 0:.1f} s)")
        first = hub.get("/agent/status")["connected_at"]

        stopped_at = time.monotonic()
        hub.stop()
        hub.start()
        up = time.monotonic() - stopped_at
        back = wait_until(lambda: hub.get("/agent/status")["online"], 35)
        total = up + (back or 0)
        check(
            back is not None and total <= 35,
            f"after a Hub restart the agent is back within 35 s ({total:.1f} s from the"
            f" stop, {up:.1f} s of it the Hub starting up)",
        )
        check(hub.get("/agent/status")["connected_at"] != first, "it is a new connection")

        check(hub.post(f"/devices/{device['id']}/revoke").status_code == 200, "revoke -> 200")
        try:
            exit_code = agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            exit_code = None
        check(
            exit_code == AgentExit.auth_rejected, f"the agent exits 3 within 10 s (got {exit_code})"
        )
    finally:
        if agent.poll() is None:
            agent.kill()
            agent.wait()

    with agent_log.open("ab") as log:
        second = subprocess.run(
            agent_argv("run"), cwd=ROOT, env=agent_env, stdout=log, stderr=log, timeout=10
        )
    check(second.returncode == AgentExit.auth_rejected, "a second start also exits 3")
    check(hub.get("/actions") == [], "no action was sent, so no window was opened")
    check(not hub.get("/agent/status")["online"], "GET /agent/status offline")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-log-out", help="copy the agent's log here")
    args = parser.parse_args()

    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    agent_env = {**os.environ, "POS_AGENT_KEYRING_SERVICE": service}
    result = 1
    with tempfile.TemporaryDirectory(dir=scratch_root, ignore_cleanup_errors=True) as tmp:
        logs = Path(tmp)
        hub = Hub(logs / "data", free_port(), logs)
        agent_env["POS_AGENT_HUB_URL"] = hub.url
        agent_log = logs / "agent.log"
        token = None
        try:
            hub.start()
            token = verify(hub, agent_env, agent_log)
            result = 0
        except CheckFailed as exc:
            print(f"\nRESULT: FAIL ({exc})")
        finally:
            hub.stop()
            forget = subprocess.run(agent_argv("forget"), cwd=ROOT, env=agent_env, timeout=30)
            gone = keyring.get_password(service, USERNAME) is None
            verdict = "PASS" if gone else "FAIL"
            print(f"{verdict}  keyring entry deleted (forget exit {forget.returncode})")
            result = result if gone else 1
            logged = (
                agent_log.read_text(encoding="utf-8", errors="replace")
                if agent_log.exists()
                else ""
            )
            hub_logs = "".join(
                p.read_text(encoding="utf-8", errors="replace") for p in logs.glob("hub-*.log")
            )
            if token is not None:
                clean = token not in logged and token not in hub_logs
                print(f"{'PASS' if clean else 'FAIL'}  the token appears in no agent or Hub log")
                result = result if clean else 1
            print("--- agent log ---")
            print(logged.rstrip())
            print("--- end agent log ---")
            if args.agent_log_out and agent_log.exists():
                shutil.copyfile(agent_log, args.agent_log_out)
    print(f"\nRESULT: {'PASS' if result == 0 else 'FAIL'} (agent_link)")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
