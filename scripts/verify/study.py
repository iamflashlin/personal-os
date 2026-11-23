# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""T-0061 on this PC: 开始学习 through the real Hub, the real agent and a real browser.

    uv run python scripts/verify/study.py [--evidence-dir .evidence/T-0061]

Starts a throwaway Hub, gives it one course whose notes link to a page served here (its
title is unique to this run), pairs an agent under a throwaway keyring name, and then:
- GET /study/plans: the plan opens the notes, titled without ".pdf";
- POST /study/sessions: the agent opens the page, verifies its window, and the session
  step reports `succeeded`; the page loaded exactly once;
- the same Idempotency-Key again returns the same session and opens nothing;
- finish moves the session to `finished`.
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
from datetime import UTC, datetime
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

CODE = "F26 MATH D001A 49 Calculus I"


def agent(command: str, env: dict[str, str], **kwargs: Any) -> Any:
    argv = [sys.executable, "-m", "apps.desktop_agent", command, *kwargs.pop("extra", [])]
    return subprocess.run(argv, cwd=ROOT, env=env, **kwargs)


def seed(data_dir: Path, notes_url: str, notes_name: str) -> None:
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
        for ext, item_type, title, url, data in [
            ("c", "canvas_course", CODE, "https://example.invalid/c", {"course_code": CODE}),
            ("m", "canvas_material", notes_name, notes_url, {"course_code": CODE, "kind": "File"}),
        ]:
            s.add(
                SyncedItemRow(
                    owner_id="local",
                    source="verify",
                    version=1,
                    integration_id=integration.id,
                    item_type=item_type,
                    external_id=ext,
                    content_hash=ext,
                    title=title,
                    body="",
                    location="",
                    url=url,
                    starts_at=None,
                    ends_at=None,
                    all_day=False,
                    data=data,
                )
            )
        s.commit()
    engine.dispose()


def settle(client: httpx.Client, session_id: str, timeout_s: float = 40) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        got = client.get(f"/study/sessions/{session_id}").json()
        if all(s["status"] != "dispatched" for s in got["steps"]) or time.monotonic() > deadline:
            return got
        time.sleep(0.25)


def verify(
    client: httpx.Client, data_dir: Path, env: dict[str, str], evidence: Path, out: dict[str, Any]
) -> None:
    with MarkerPage(background=PAGE_RGB, close_after_s=15) as page:
        seed(data_dir, page.url, page.title + ".pdf")
        course_map = {
            "course_code": "MATH D001A",
            "material": page.title + ".pdf",
            "concepts": [
                {"key": "ch1", "kind": "chapter", "title": "Functions"},
                {"key": "1.1", "kind": "section", "parent": "ch1", "title": "Graphs", "page": 3},
            ],
        }
        put = client.put("/academic/maps/MATH D001A", json=course_map)
        check(put.status_code == 200, f"course map stored ({put.status_code})")
        plan = client.get("/study/plans/MATH D001A").json()
        out["plan"] = plan
        check(plan["next"]["key"] == "1.1", f"plan suggests 1.1 ({plan['next']})")
        check(
            [s["params"] for s in plan["steps"]]
            == [{"url": page.url, "expect_title_contains": page.title}],
            "plan opens the notes, expecting the title without .pdf",
        )

        offline = client.post(
            "/study/sessions",
            json={"course_code": "MATH D001A"},
            headers={"Idempotency-Key": "verify-offline"},
        )
        check(offline.status_code == 503, f"no agent yet -> 503 ({offline.status_code})")

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

            started = client.post(
                "/study/sessions",
                json={"course_code": "MATH D001A"},
                headers={"Idempotency-Key": "verify-study-1"},
            )
            check(started.status_code == 201, f"POST /study/sessions -> {started.status_code}")
            session = settle(client, started.json()["id"])
            out["session"] = session
            (step,) = session["steps"]
            check(step["status"] == "succeeded", f"step {step['status']}: {step['message']}")
            run = client.get(f"/actions/{step['action_run_id']}").json()
            out["action_run"] = run
            check(page.title in run["evidence"][0]["data"]["title"], "evidence names our page")
            check(page.loads == 1, f"page loaded once ({page.loads})")

            again = client.post(
                "/study/sessions",
                json={"course_code": "MATH D001A"},
                headers={"Idempotency-Key": "verify-study-1"},
            )
            check(again.json()["id"] == session["id"], "same key -> same session")
            time.sleep(3)
            check(page.loads == 1, f"still one page load after the replay ({page.loads})")

            done = client.post(
                f"/study/sessions/{session['id']}/finish",
                json={"version": session["version"], "note": "verify"},
            )
            check(done.status_code == 200 and done.json()["status"] == "finished", "finished")
            last = client.get("/study/plans/MATH D001A").json()["last"]
            check(last is not None and last["finished_at"] is not None, "plan shows last session")
            out["finished"] = done.json()
            remembered = [
                m
                for m in client.get("/memories").json()
                if m["source_ref"] == f"study:{session['id']}"
            ]
            out["memory"] = remembered
            check(
                len(remembered) == 1 and "学完了 MATH D001A" in remembered[0]["body"],
                "the finished session is in 记忆 (T-0072)",
            )
        finally:
            client.post(f"/devices/{device['id']}/revoke")
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(ROOT / "data" / "verify" / "study"))
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
