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
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from hub import CheckFailed, check, running_hub  # noqa: E402
from playwright.sync_api import Locator, Page, sync_playwright  # noqa: E402

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


MEMORY = "我更喜欢早上学习，晚上复习英语"
AI_GUESS = "Prefers studying in short sessions"
AI_WRONG = "Usually studies after midnight"
AI_FIXED = "Usually studies before 10pm"
CORRECTED = "我更喜欢晚上学习，早上跑步"
SECRET = "门禁密码 6291"


def _memory_bodies(api: httpx.Client) -> dict[str, dict[str, Any]]:
    return {m["body"]: m for m in api.get("/memories").json()}


def _hub_search(api: httpx.Client, q: str) -> list[str]:
    return [h["memory"]["body"] for h in api.get("/memories/search", params={"q": q}).json()]


def _page_search(page: Page, q: str, expected: list[str]) -> list[str]:
    """Search in the page; wait (up to 5 s) for the list to settle on `expected`."""
    box = page.get_by_role("search")
    box.get_by_label("搜索", exact=False).fill(q)
    box.get_by_role("button", name="搜索").click()
    bodies = page.get_by_test_id("memories").get_by_test_id("memory-body")
    deadline = time.monotonic() + 5
    shown = bodies.all_inner_texts()
    while shown != expected and time.monotonic() < deadline:
        time.sleep(0.1)
        shown = bodies.all_inner_texts()
    print(f"page search {q!r} -> {shown}", flush=True)
    return shown


def _seed_guess(api: httpx.Client, body: str) -> None:
    guess = api.post(
        "/memories",
        json={"kind": "preference", "body": body, "provenance": "ai_inferred", "confidence": 0.4},
    )
    check(guess.status_code == 201, f"seed AI-inferred memory {body!r} over HTTP")


def verify_memory_view(page: Page, api: httpx.Client, out: Path, errors: list[str]) -> None:
    """T-0009: the memory page, driven like a person, checked against the Hub API."""
    _seed_guess(api, AI_GUESS)
    _seed_guess(api, AI_WRONG)
    page.get_by_role("button", name="记忆").click()
    view = page.get_by_test_id("memories")
    view.get_by_text(AI_GUESS).wait_for()

    def row_of(body: str) -> Locator:
        # By id, not text: while editing, the text sits in an input.
        return page.get_by_test_id(f"memory-{_memory_bodies(api)[body]['id']}")

    form = page.get_by_role("form", name="添加记忆")
    form.get_by_label("要记住的内容").fill(MEMORY)
    form.get_by_label("类型").select_option(label="偏好")
    form.get_by_role("button", name="记住").click()
    view.get_by_text(MEMORY).wait_for()
    check(_memory_bodies(api)[MEMORY]["kind"] == "preference", "form stored kind 偏好")
    shot(page, out, "05-memory-added")

    hub = _hub_search(api, "英语")
    check(
        _page_search(page, "英语", hub) == hub == [MEMORY], "2-character search 英语: page == Hub"
    )
    shot(page, out, "06-memory-search")
    page.get_by_role("search").get_by_role("button", name="显示全部").click()

    row_of(AI_GUESS).get_by_role("button", name="确认没错").click()
    row_of(AI_GUESS).get_by_text("已确认").wait_for()
    stored = _memory_bodies(api)[AI_GUESS]
    check(
        stored["provenance"] == "user_confirmed" and stored["confidence"] == 1,
        "确认没错 makes an AI guess user_confirmed in the Hub",
    )

    wrong = row_of(AI_WRONG)
    wrong.get_by_role("button", name="改正").click()
    wrong.get_by_label("改正为").fill(AI_FIXED)
    wrong.get_by_role("button", name="保存改正").click()
    view.get_by_text(AI_FIXED).wait_for()
    fixed = _memory_bodies(api)[AI_FIXED]
    check(
        fixed["provenance"] == "user_confirmed" and fixed["confidence"] == 1,
        "correcting an AI guess makes it user_confirmed in the Hub",
    )

    editing = row_of(MEMORY)
    memory = _memory_bodies(api)[MEMORY]
    editing.get_by_role("button", name="改正").click()
    bumped = api.patch(
        f"/memories/{memory['id']}", json={"version": memory["version"], "source_ref": "chat"}
    )
    check(bumped.status_code == 200, "someone else changes the memory while the page edits it")
    editing.get_by_label("改正为").fill(CORRECTED)
    editing.get_by_role("button", name="保存改正").click()
    alert = page.get_by_role("alert")
    alert.wait_for()
    check("409" in alert.inner_text(), "stale save shows a 409 alert and keeps the edit open")
    # That 409 was provoked on purpose; drop exactly its console lines, nothing else.
    provoked = [e for e in errors if "409" in e]
    check(len(provoked) == 2, f"the provoked 409 is the only one logged ({provoked})")
    for line in provoked:
        errors.remove(line)
    editing.get_by_role("button", name="保存改正").click()
    view.get_by_text(CORRECTED).wait_for()
    bodies = _memory_bodies(api)
    check(
        CORRECTED in bodies and MEMORY not in bodies,
        "retry after 409 saves the correction in place (no duplicate)",
    )
    hub = _hub_search(api, "晚上学习")
    check(hub == [CORRECTED], "Hub search finds the new wording")
    check(_page_search(page, "晚上学习", hub) == hub, "page search shows the same result")
    shot(page, out, "07-memory-corrected")
    page.get_by_role("search").get_by_role("button", name="显示全部").click()

    form.get_by_label("要记住的内容").fill(SECRET)
    form.get_by_label("敏感度").select_option(label="机密")
    form.get_by_role("button", name="记住").click()
    view.get_by_text("机密，按“显示”查看").wait_for()
    check(_memory_bodies(api)[SECRET]["sensitivity"] == "secret", "form stored sensitivity 机密")
    secret = row_of(SECRET)
    body = secret.get_by_test_id("memory-body")
    check(SECRET not in body.inner_text(), "secret body masked until 显示")
    check(secret.get_by_role("button", name="改正").is_disabled(), "改正 disabled while masked")
    shot(page, out, "08-memory-secret-masked")
    secret.get_by_role("button", name="显示").click()
    check(SECRET in body.inner_text(), "显示 reveals the secret body")
    secret.get_by_role("button", name="隐藏").click()
    check(
        _hub_search(api, "门禁") == [] == _page_search(page, "门禁", []),
        "secret left out of search",
    )
    page.get_by_role("search").get_by_role("button", name="显示全部").click()

    target = row_of(CORRECTED)
    target.get_by_role("button", name="删除").click()
    target.get_by_role("button", name="确定删除").wait_for()
    check(CORRECTED in _memory_bodies(api), "a single click on 删除 deletes nothing")
    target.get_by_role("button", name="确定删除").click()
    view.get_by_text(CORRECTED).wait_for(state="detached")
    check(CORRECTED not in _memory_bodies(api), "deleted after 确定删除")


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
            verify_memory_view(page, api, out, errors)
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
