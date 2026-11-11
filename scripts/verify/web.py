# ruff: noqa: RUF001  (the page's Chinese labels use full-width punctuation)
"""Real-behaviour check of the web UI in Microsoft Edge, driven by Playwright.

    uv run python scripts/verify/web.py [--out .evidence/T-0004/screenshots] [--headed]

Builds apps/web, starts the real Hub (which serves the build at `/`) on a free port with
a fresh data dir, seeds a goal and a project over HTTP, then uses the page like a person:
create a task with the form, mark it done with a note, and confirm through the Hub API
that the task is done with exactly one user-confirmation Evidence row. Screenshots show
only this page in a browser this script launched. Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hub import CheckFailed, check, running_hub  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

TASK_TITLE = "读第 3 次实验的说明"
NOTE = "读完了，记下了三个问题"


def build_web() -> None:
    pnpm = shutil.which("pnpm")
    check(pnpm is not None, "pnpm is on PATH")
    result = subprocess.run(
        [pnpm or "pnpm", "--dir", "apps/web", "build"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    print(result.stdout.strip(), flush=True)
    check(result.returncode == 0, "pnpm --dir apps/web build")
    check((ROOT / "apps" / "web" / "dist" / "index.html").is_file(), "apps/web/dist/index.html")


def shot(page: Page, out: Path, name: str) -> None:
    path = out / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"screenshot {path}", flush=True)


def run(out: Path, headed: bool) -> None:
    build_web()
    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=scratch_root, ignore_cleanup_errors=True) as tmp,
        running_hub(Path(tmp) / "data") as api,
    ):
        goal = api.post("/goals", json={"title": "通过 CIS 课程"}).json()
        project = api.post("/projects", json={"title": "CIS 实验 3", "goal_id": goal["id"]})
        check(project.status_code == 201, "seed a goal and a project over HTTP")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=not headed)
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "response",
                lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None,
            )

            page.goto(str(api.base_url))
            page.get_by_text("通过 CIS 课程").first.wait_for()
            check(
                page.get_by_test_id("goals").get_by_text("通过 CIS 课程").count() == 1,
                "goals column lists the seeded goal",
            )
            check(
                page.get_by_test_id("projects").get_by_text("CIS 实验 3").count() == 1,
                "projects column lists the seeded project",
            )
            shot(page, out, "01-loaded")

            page.get_by_label("任务标题").fill(TASK_TITLE)
            page.get_by_label("所属项目").select_option(label="CIS 实验 3")
            page.get_by_label("标签").fill("course:CIS")
            # A double-click must still create one task (the button is disabled while pending).
            page.get_by_role("button", name="添加任务").dblclick()
            row = page.locator("li.task", has_text=TASK_TITLE)
            row.wait_for()
            page.get_by_role("button", name="添加任务").wait_for()
            check(row.count() == 1, "double-clicking 添加任务 shows one task")
            check(
                row.get_by_test_id("task-status").inner_text() == "未开始",
                "new task appears as 未开始",
            )
            check("自己做" in row.inner_text(), "course:CIS task shows 自己做 (human_led)")
            shot(page, out, "02-created")

            row.get_by_role("button", name="标记完成").click()
            row.get_by_label("完成说明").fill(NOTE)
            shot(page, out, "03-confirming")
            row.get_by_role("button", name="确认，我已完成").click()
            row.locator(".badge.done").wait_for()
            check(
                row.get_by_test_id("task-status").inner_text() == "已完成",
                "task shows 已完成 after confirming",
            )
            shot(page, out, "04-done")
            page.reload()
            row.locator(".badge.done").wait_for()
            check(
                row.get_by_test_id("task-status").inner_text() == "已完成",
                "still 已完成 after reloading the page",
            )
            check(not errors, f"no browser console errors ({errors})")
            browser.close()

        tasks = [t for t in api.get("/tasks").json() if t["title"] == TASK_TITLE]
        check(len(tasks) == 1, "Hub has exactly one task created through the form")
        task = tasks[0]
        check(task["status"] == "done", "Hub reports the task as done")
        check(task["execution_mode"] == "human_led", "Hub stored execution_mode human_led")
        evidence = api.get(f"/tasks/{task['id']}/evidence").json()
        print(f"GET /tasks/{task['id']}/evidence -> {evidence}", flush=True)
        check(len(evidence) == 1, "exactly one Evidence row")
        check(evidence[0]["kind"] == "user_confirmation", "Evidence kind is user_confirmation")
        check(evidence[0]["note"] == NOTE, "Evidence keeps the note typed in the page")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / ".evidence" / "T-0004" / "screenshots")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        run(args.out, args.headed)
    except CheckFailed as exc:
        print(f"\nRESULT: FAIL ({exc})")
        return 1
    print("\nRESULT: PASS (web)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
