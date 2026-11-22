"""T-0063 on this PC: the supervisor keeps the desktop agent running, only when enabled.

    uv run python scripts/verify/agent_always_on.py [--evidence-dir .evidence/T-0063]

Runs the real scripts/run/run-hub.ps1 from this checkout with a throwaway data folder, a
free port and a throwaway keyring name (nothing of the always-on Hub is touched), then:
- without agent.enabled, no agent runs;
- enable-agent.ps1 pairs the agent and writes agent.enabled; the agent comes online;
- the agent process is killed; the supervisor starts it again;
- the device is revoked; the agent exits 3 and is NOT restarted (needs pairing);
- enable-agent.ps1 again: paired anew, online again;
- enable-agent.ps1 -Disable: the agent stops and stays stopped;
- stop-hub.ps1 stops the supervisor, the Hub and the agent; nothing of ours is left.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import keyring
from keyring.errors import PasswordDeleteError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.desktop_agent.token_store import USERNAME  # noqa: E402

RUN = ROOT / "scripts" / "run"
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


class Failed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise Failed(message)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait(condition: Any, timeout_s: float) -> float | None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            if condition():
                return round(time.monotonic() - start, 1)
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    return None


def ours(name: str) -> list[int]:
    """python.exe processes running `name` from this checkout."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='uv.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{name}*' -and $_.CommandLine -notlike "
            "'*verify*' } | ForEach-Object { \"$($_.ProcessId) $($_.ExecutablePath)\" }",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split("\n")
    root = str(ROOT).lower()
    found = []
    for line in out:
        if not line.strip():
            continue
        pid, _, exe = line.strip().partition(" ")
        # Only interpreters from this checkout's .venv: a uv.exe cannot be told apart from
        # the always-on Hub's own (same command line), which must be left running.
        if exe.lower().startswith(root):
            found.append(int(pid))
    return found


def ps(script: str, *args: str, env: dict[str, str], timeout: int = 120) -> tuple[int, str]:
    done = subprocess.run(
        [*PS, str(RUN / script), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return done.returncode, (done.stdout + done.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(ROOT / "data" / "verify" / "always-agent"))
    args = parser.parse_args()
    evidence = Path(args.evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / "data" / "verify"
    scratch.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="always-agent-", dir=scratch))
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    env = {
        **os.environ,
        "POS_HUB_PORT": str(port),
        "POS_AGENT_HUB_URL": url,
        "POS_AGENT_KEYRING_SERVICE": service,
        "POS_AGENT_HEARTBEAT_S": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("POS_HUB_HOST", None)
    common = ["-CopyDir", str(ROOT), "-DataDir", str(data_dir)]
    out: dict[str, Any] = {"port": port}
    supervisor: subprocess.Popen[bytes] | None = None
    outcome = 1
    api = httpx.Client(base_url=url, timeout=5)

    def online() -> bool:
        return bool(api.get("/agent/status").json()["online"])

    try:
        supervisor = subprocess.Popen(
            [*PS, str(RUN / "run-hub.ps1"), *common],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        up = wait(lambda: api.get("/health").json()["status"] == "ok", 90)
        check(up is not None, f"the supervisor started the Hub on {url} ({up}s)")
        time.sleep(8)
        check(not online(), "without agent.enabled no agent runs (8 s)")
        check(not (data_dir / "agent.pid").exists(), "and no agent.pid is written")

        enable = ["-HubUrl", url, *common]
        code, text = ps("enable-agent.ps1", *enable, env=env)
        out["enable_1"] = text
        check(code == 0, f"enable-agent.ps1 exits 0 ({text.splitlines()[-1] if text else ''})")
        check((data_dir / "agent.enabled").exists(), "agent.enabled written")
        check(keyring.get_password(service, USERNAME) is not None, "token in Credential Manager")
        check(online(), "the agent is online")

        first_pid = int((data_dir / "agent.pid").read_text().strip())
        subprocess.run(["taskkill", "/PID", str(first_pid), "/T", "/F"], capture_output=True)
        gone = wait(lambda: not online(), 20)
        check(gone is not None, f"after killing the agent the Hub sees it go ({gone}s)")
        back = wait(online, 40)
        check(back is not None, f"the supervisor starts it again ({back}s)")
        second_pid = int((data_dir / "agent.pid").read_text().strip())
        check(second_pid != first_pid, "a new agent process")

        (device,) = [d for d in api.get("/devices").json() if d.get("revoked_at") is None]
        check(api.post(f"/devices/{device['id']}/revoke").status_code == 200, "revoke device")
        log = data_dir / "logs" / "hub.log"
        held = wait(lambda: "needs pairing" in log.read_text("utf-8"), 30)
        check(held is not None, f"the agent exits 3; the log says 'needs pairing' ({held}s)")
        time.sleep(15)
        check(not online(), "and does not restart it (15 s)")

        code, text = ps("enable-agent.ps1", *enable, env=env)
        out["enable_2"] = text
        check(code == 0 and online(), "enable-agent.ps1 again: paired anew and online")

        code, text = ps("enable-agent.ps1", "-Disable", *enable, env=env)
        out["disable"] = text
        check(code == 0, "enable-agent.ps1 -Disable exits 0")
        check(not (data_dir / "agent.enabled").exists(), "agent.enabled removed")
        time.sleep(10)
        check(not online(), "the agent stays stopped (10 s)")

        # One more agent, so stop-hub.ps1 has all three processes to stop.
        code, _ = ps("enable-agent.ps1", *enable, env=env)
        check(code == 0 and online(), "re-enabled for the stop test")
        code, text = ps("stop-hub.ps1", *common, env=env)
        check(code == 0, "stop-hub.ps1 exits 0")
        down = wait(lambda: supervisor is not None and supervisor.poll() is not None, 20)
        check(down is not None, "the supervisor is gone")
        hub_gone = wait(lambda: api.get("/health").status_code < 0, 10) is None
        try:
            api.get("/health")
            still = True
        except httpx.TransportError:
            still = False
        check(hub_gone and not still, "the Hub no longer answers")
        left = ours("apps.desktop_agent") + ours("apps.hub")
        check(not left, f"no Hub or agent process of this checkout is left ({left})")
        outcome = 0
        print("\nRESULT: PASS")
    except Failed as exc:
        print(f"\nRESULT: FAIL ({exc})")
    finally:
        api.close()
        if supervisor is not None and supervisor.poll() is None:
            ps("stop-hub.ps1", *common, env=env)
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(service, USERNAME)
        gone = keyring.get_password(service, USERNAME) is None
        print(f"{'PASS' if gone else 'FAIL'}  keyring entry removed")
        outcome = outcome if gone else 1
        supervisor_log = data_dir / "logs" / "hub.log"
        if supervisor_log.exists():
            shutil.copy(supervisor_log, evidence / "supervisor.log")
        out["outcome"] = outcome
        (evidence / "result.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        shutil.rmtree(data_dir, ignore_errors=True)
    return outcome


if __name__ == "__main__":
    sys.exit(main())
