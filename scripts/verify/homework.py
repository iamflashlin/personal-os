# ruff: noqa: RUF002  (the docstring names a Chinese button as written)
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""T-0066 on this PC: 作业 through the real Hub, the real agent and a real browser.

    uv run python scripts/verify/homework.py [--evidence-dir .evidence/T-0066]

Starts a throwaway Hub with one Canvas assignment due in 3 hours whose page is served
here (its title is unique to this run), pairs an agent under a throwaway keyring name,
and then:
- GET /homework: the assignment is due within 24 h and is the reminder;
- 去提交 with no agent: 503 and nothing stored;
- 去提交 with the agent: it opens the page, verifies its window, the run reports
  `succeeded`; the page loaded exactly once;
- the same Idempotency-Key again opens nothing;
- 我交了，查一下 queues a Canvas sync.
Then revokes the agent and removes the keyring entry. Nothing is clicked or typed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import keyring
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub import CheckFailed, check, running_hub  # noqa: E402
from spike_printwindow import PAGE_RGB, MarkerPage  # noqa: E402

from apps.desktop_agent.token_store import USERNAME  # noqa: E402
from apps.hub.core.db import DB_FILENAME  # noqa: E402
from apps.hub.integrations.models import IntegrationRow, SyncedItemRow  # noqa: E402


def agent(command: str, env: dict[str, str], **kwargs: Any) -> Any:
    argv = [sys.executable, "-m", "apps.desktop_agent", command, *kwargs.pop("extra", [])]
    return subprocess.run(argv, cwd=ROOT, env=env, **kwargs)


def seed(data_dir: Path, url: str, title: str) -> str:
    engine = create_engine(f"sqlite:///{data_dir / DB_FILENAME}")
    with Session(engine) as s:
        integration = IntegrationRow(
            owner_id="local",
            source="verify",
            version=1,
            kind="canvas",
            name="Canvas",
            credential_name="x",
            interval_s=900,
            config={},
            status="ok",
            last_error="",
            cursor={},
        )
        s.add(integration)
        s.flush()
        row = SyncedItemRow(
            owner_id="local",
            source="verify",
            version=1,
            integration_id=integration.id,
            item_type="canvas_assignment",
            external_id="1:1",
            content_hash="1:1",
            title=title,
            body="",
            location="",
            url=url,
            starts_at=datetime.now(UTC) + timedelta(hours=3),
            ends_at=None,
            all_day=False,
            data={
                "course": "F26 ENGL C1000 Reading",
                "course_code": "ENGL C1000",
                "points_possible": 10,
                "submission_state": "unsubmitted",
                "missing": False,
            },
        )
        s.add(row)
        s.commit()
        item_id = row.id
    engine.dispose()
    return item_id


def settle(client: httpx.Client, action_id: str, timeout_s: float = 40) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        run = client.get(f"/actions/{action_id}").json()
        if run["status"] != "dispatched" or time.monotonic() > deadline:
            return run
        time.sleep(0.25)


def verify(
    client: httpx.Client, data_dir: Path, env: dict[str, str], evidence: Path, out: dict[str, Any]
) -> None:
    with MarkerPage(background=PAGE_RGB, close_after_s=15) as page:
        item_id = seed(data_dir, page.url, page.title)
        board = client.get("/homework").json()
        out["board"] = board
        check([h["id"] for h in board["soon"]] == [item_id], "assignment is due within 24 h")
        check(board["reminder"] and board["reminder"]["id"] == item_id, "it is the reminder")

        offline = client.post(
            f"/homework/{item_id}/open", headers={"Idempotency-Key": "verify-offline"}
        )
        check(offline.status_code == 503, f"no agent yet -> 503 ({offline.status_code})")
        check(client.get("/actions").json() == [], "nothing stored while offline")

        code = client.post("/devices/pairing-codes").json()["code"]
        paired = agent("pair", env, extra=["--code", code], capture_output=True)
        check(paired.returncode == 0, "agent paired")
        (device,) = client.get("/devices").json()
        log_path = evidence / "agent.log"
        with log_path.open("wb") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "apps.desktop_agent", "run"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
        try:
            deadline = time.monotonic() + 15
            while not client.get("/agent/status").json()["online"]:
                if time.monotonic() > deadline:
                    check(False, "agent online within 15 s")
                time.sleep(0.2)
            check(True, "agent online within 15 s")

            opened = client.post(
                f"/homework/{item_id}/open", headers={"Idempotency-Key": "verify-open-1"}
            )
            check(opened.status_code == 202, f"POST /homework/.../open -> {opened.status_code}")
            run = settle(client, opened.json()["action"]["id"])
            out["action_run"] = run
            check(run["status"] == "succeeded", f"run {run['status']}: {run['message']}")
            check(run["params"]["url"] == page.url, "the agent opened the assignment's own URL")
            check(page.title in run["evidence"][0]["data"]["title"], "evidence names our page")
            check(page.loads == 1, f"page loaded once ({page.loads})")

            again = client.post(
                f"/homework/{item_id}/open", headers={"Idempotency-Key": "verify-open-1"}
            )
            check(again.json()["replayed"] is True, "same key -> replayed")
            time.sleep(3)
            check(page.loads == 1, f"still one page load after the replay ({page.loads})")

            asked = client.post("/homework/check")
            out["check"] = asked.json()
            check(asked.status_code == 202 and len(asked.json()["job_ids"]) == 1, "sync queued")
        finally:
            client.post(f"/devices/{device['id']}/revoke")
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(ROOT / "data" / "verify" / "homework"))
    args = parser.parse_args()
    evidence = Path(args.evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    env = {**os.environ, "POS_AGENT_KEYRING_SERVICE": service}
    out: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat()}
    outcome = 1
    scratch = ROOT / "data" / "verify"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, ignore_cleanup_errors=True) as tmp:
        data_dir = Path(tmp) / "data"
        try:
            with running_hub(data_dir) as client:
                env["POS_AGENT_HUB_URL"] = str(client.base_url).rstrip("/")
                verify(client, data_dir, env, evidence, out)
            outcome = 0
            print("\nRESULT: PASS")
        except CheckFailed as exc:
            print(f"\nRESULT: FAIL ({exc})")
        finally:
            agent("forget", env, capture_output=True, timeout=30)
            gone = keyring.get_password(service, USERNAME) is None
            print(f"{'PASS' if gone else 'FAIL'}  keyring entry removed")
            outcome = outcome if gone else 1
    out["outcome"] = outcome
    (evidence / "result.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return outcome


if __name__ == "__main__":
    sys.exit(main())
