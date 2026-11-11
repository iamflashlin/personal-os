# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""S2 acceptance on this PC: the real Hub, the real agent, real windows.

    uv run python scripts/verify/desktop_agent.py [--evidence-dir .evidence/T-0008]

Starts the Hub, pairs an agent (token under a throwaway keyring service name), runs it,
and asks it to:
- open our own marker page (served here; counts real page loads), then checks the window
  independently, saves a crop of only that page, and proves a replay executes nothing;
- open a fresh temp folder in VS Code, then closes only that VS Code window.
Then revokes the agent, and removes the temp folder and the keyring entry.
Nothing is clicked, typed or focused by this script.

Exit 0: all passed. Exit 4: everything else passed but VS Code's `code` command is
missing (needs_user); the card is then blocked, not done. Exit 1: a check failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import keyring

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub import CheckFailed, check, running_hub  # noqa: E402
from spike_printwindow import PAGE_RGB, MarkerPage, page_colour_share, wait_gone  # noqa: E402

from apps.desktop_agent.connection import AgentExit  # noqa: E402
from apps.desktop_agent.token_store import USERNAME  # noqa: E402
from apps.desktop_agent.windows_adapter import WindowsAdapter, capture_document  # noqa: E402

NEEDS_CODE = 4


def agent(command: str, env: dict[str, str], **kwargs: Any) -> Any:
    argv = [sys.executable, "-m", "apps.desktop_agent", command, *kwargs.pop("extra", [])]
    return subprocess.run(argv, cwd=ROOT, env=env, **kwargs)


def settle(client: httpx.Client, run_id: str, timeout_s: float = 40) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        run = client.get(f"/actions/{run_id}").json()
        if run["status"] != "dispatched" or time.monotonic() > deadline:
            return run
        time.sleep(0.2)


def act(client: httpx.Client, key: str, name: str, params: dict[str, Any]) -> httpx.Response:
    return client.post(
        "/actions", json={"name": name, "params": params}, headers={"Idempotency-Key": key}
    )


def verify(client: httpx.Client, env: dict[str, str], evidence: Path, result: dict[str, Any]):
    code = client.post("/devices/pairing-codes").json()["code"]
    check(agent("pair", env, extra=["--code", code], capture_output=True).returncode == 0, "pair")
    (device,) = client.get("/devices").json()
    log_path = evidence / "agent.log"
    proc: subprocess.Popen[bytes] | None = None
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "apps.desktop_agent", "run"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
    desktop = WindowsAdapter()
    try:
        deadline = time.monotonic() + 15
        while not client.get("/agent/status").json()["online"]:
            if time.monotonic() > deadline:
                check(False, "agent online within 15 s")
            time.sleep(0.2)
        check(True, "agent online within 15 s")

        with MarkerPage(background=PAGE_RGB, close_after_s=20) as page:
            params = {"url": page.url, "expect_title_contains": page.title}
            sent = act(client, "verify-url-1", "open_url", params)
            check(sent.status_code == 202, f"POST open_url -> {sent.status_code}")
            run = settle(client, sent.json()["id"])
            result["open_url"] = run
            check(run["status"] == "succeeded", f"open_url {run['status']}: {run['message']}")
            check(
                page.title in run["evidence"][0]["data"]["title"], "agent evidence names our page"
            )
            window = desktop.wait_for_window(page.title, 10)
            check(window is not None, "the script sees the marker window on its own")
            assert window is not None
            image = capture_document(window, page.title)
            check(image is not None, "captured our page with PrintWindow + its UIA Document")
            share = page_colour_share(image)
            check(share > 0.6, f"the crop shows only our page ({share:.0%} page colour)")
            # Written only after the check, so a wrong crop never reaches the disk (D5).
            image.save(evidence / "open_url_page.png")
            check(page.loads == 1, f"page loaded once (beacons: {page.loads})")

            replay = act(client, "verify-url-1", "open_url", params)
            check(
                replay.headers.get("Idempotent-Replayed") == "true"
                and replay.json()["id"] == run["id"],
                "same key replays the same run id",
            )
            time.sleep(3)
            check(page.loads == 1, f"still one page load after the replay ({page.loads})")
            runs = [
                r for r in client.get("/actions").json() if r["idempotency_key"] == "verify-url-1"
            ]
            check(len(runs) == 1, "one action_run row for the key")
            delivered = log_path.read_text(encoding="utf-8").count("action open_url")
            check(delivered == 1, f"the agent received the action once ({delivered} log line)")
            changed = {**params, "expect_title_contains": page.title + "-other"}
            other = act(client, "verify-url-1", "open_url", changed)
            check(other.status_code == 422, "same key, different body -> 422")
            result["beacons"] = page.loads
            gone = wait_gone(desktop, page.title, 30)
            print(f"info   our page closed itself: {gone}", flush=True)
            result["page_closed_itself"] = gone

        scratch = ROOT / "data" / "verify"
        folder = Path(tempfile.mkdtemp(prefix="pos-verify-", dir=scratch))
        try:
            sent = act(client, "verify-folder-1", "open_folder_in_editor", {"path": str(folder)})
            run = settle(client, sent.json()["id"])
            result["open_folder"] = run
            if run["status"] == "needs_user":
                print(f"NEEDS_USER  open_folder_in_editor: {run['message']}", flush=True)
                result["needs_user"] = run["message"]
            else:
                check(
                    run["status"] == "succeeded", f"open_folder {run['status']}: {run['message']}"
                )
                window = desktop.wait_for_window(folder.name, 10)
                check(window is not None, f"a VS Code window titled with {folder.name}")
                assert window is not None
                desktop.close(window)  # the only window this script closes
                closed = desktop.wait_for_window(folder.name, 0.1) is None
                for _ in range(40):
                    if closed:
                        break
                    time.sleep(0.25)
                    closed = desktop.wait_for_window(folder.name, 0.1) is None
                check(closed, "closed only our VS Code window")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            check(not folder.exists(), "temp folder removed")

        check(client.post(f"/devices/{device['id']}/revoke").status_code == 200, "revoke")
        exit_code = proc.wait(timeout=10)
        check(exit_code == AgentExit.auth_rejected, f"agent exits 3 after revoke ({exit_code})")
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
    again = agent("run", env, capture_output=True, timeout=15)
    check(again.returncode == AgentExit.auth_rejected, "a restarted agent also exits 3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(ROOT / "data" / "verify" / "desktop"))
    args = parser.parse_args()
    evidence = Path(args.evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    env = {**os.environ, "POS_AGENT_KEYRING_SERVICE": service}
    result: dict[str, Any] = {}
    outcome = 1
    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root, ignore_cleanup_errors=True) as tmp:
        try:
            with running_hub(Path(tmp) / "data") as client:
                env["POS_AGENT_HUB_URL"] = str(client.base_url).rstrip("/")
                verify(client, env, evidence, result)
            outcome = NEEDS_CODE if "needs_user" in result else 0
        except CheckFailed as exc:
            print(f"\nRESULT: FAIL ({exc})")
        finally:
            agent("forget", env, capture_output=True, timeout=30)
            gone = keyring.get_password(service, USERNAME) is None
            print(f"{'PASS' if gone else 'FAIL'}  keyring entry removed")
            if not gone:
                outcome = 1
    result["outcome"] = outcome
    (evidence / "result.json").write_text(json.dumps(result, indent=2, default=str))
    label = {0: "PASS", NEEDS_CODE: "NEEDS_USER (install VS Code's `code` command)"}
    print(f"\nRESULT: {label.get(outcome, 'FAIL')} (desktop_agent)")
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())
