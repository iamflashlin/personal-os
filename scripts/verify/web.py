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
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import keyring  # noqa: E402
from hub import CheckFailed, FakeCanvas, check, fake_mail, recent, running_hub  # noqa: E402
from playwright.sync_api import Dialog, Locator, Page, sync_playwright  # noqa: E402

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
    base = str(api.base_url).rstrip("/")
    response_line = f"HTTP 409 {base}/memories/{memory['id']}"
    console_line = "Failed to load resource: the server responded with a status of 409 (Conflict)"
    provoked = [e for e in errors if e in (response_line, console_line)]
    check(
        sorted(provoked) == sorted([response_line, console_line]),
        f"exactly the provoked 409 was logged ({provoked})",
    )
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


class FeedServer:
    """A calendar feed on 127.0.0.1 with events in the next few days; failures on demand."""

    def __init__(self) -> None:
        self.token = f"feedtoken-{uuid.uuid4().hex[:16]}"
        self.status = 200
        self.titles = {"lab": "Lab 3 实验报告", "quiz": "Quiz 2 小测", "today": "今天截止的作业"}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = server.calendar().encode()
                self.send_response(server.status)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}/feeds/{self.token}.ics"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def calendar(self) -> str:
        soon = datetime.now(UTC) + timedelta(days=2)
        later = datetime.now(UTC) + timedelta(days=5)
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        for uid, start in (("lab", soon), ("quiz", later)):
            lines += ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{self.titles[uid]}"]
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}Z", "END:VEVENT"]
        # An all-day item for today (stored at UTC midnight): it must still be listed.
        lines += ["BEGIN:VEVENT", "UID:today", f"SUMMARY:{self.titles['today']}"]
        lines += [f"DTSTART;VALUE=DATE:{datetime.now():%Y%m%d}", "END:VEVENT"]
        return "\r\n".join([*lines, "END:VCALENDAR", ""])

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()


def verify_connections_view(
    page: Page, api: httpx.Client, out: Path, errors: list[str], service: str, hub_log: Path
) -> None:
    feed = FeedServer()
    owner = os.environ.get("POS_OWNER_ID", "local")
    leaks: list[str] = []

    def watch(request: Any) -> None:
        # The link may travel in exactly one kind of request: PUT /credentials/<name>.
        carried = feed.token in request.url or feed.token in (request.post_data or "")
        if carried and not (request.method == "PUT" and "/credentials/" in request.url):
            leaks.append(f"{request.method} {request.url.split('?')[0]}")

    page.on("request", watch)
    key: str | None = None
    try:
        page.get_by_role("button", name="连接", exact=True).click()
        form = page.get_by_role("form", name="添加日历订阅")
        form.get_by_label("名称").fill("Canvas 日历")
        form.get_by_label("订阅链接（不会再显示）").fill(feed.url)
        form.get_by_role("button", name="连接").click()
        upcoming = page.get_by_test_id("upcoming")
        # No click: the schedule is due at once, and the page refreshes itself every 10 s.
        upcoming.get_by_text(feed.titles["lab"]).wait_for(timeout=40_000)
        check(True, "the background sync fills 接下来 14 天 without a click")
        check(upcoming.get_by_test_id("upcoming-item").count() == 3, "three upcoming items")
        check(upcoming.get_by_text(feed.titles["today"]).count() == 1, "today's all-day item shows")
        (stored,) = api.get("/credentials").json()
        key = f"{owner}:{stored['name']}"
        check(keyring.get_password(service, key) == feed.url, "the link is in Credential Manager")
        check(form.get_by_label("订阅链接（不会再显示）").input_value() == "", "link field emptied")
        check(feed.token not in page.content(), "the feed token is nowhere in the page")
        (integration,) = api.get("/integrations").json()
        check(integration["status"] == "ok", "the Hub reports the connection as 正常")
        shot(page, out, "09-connected")
        sched_kind = page.get_by_test_id("kind-schedule")
        check(
            "正常" in sched_kind.inner_text() and "最近成功" in sched_kind.inner_text(),
            "数据来源总览: 日程 is 正常 with its last success time",
        )

        feed.titles["lab"] = "Lab 3 实验报告（改期）"
        page.get_by_role("button", name="立即同步").click()
        upcoming.get_by_text(feed.titles["lab"]).wait_for(timeout=40_000)
        items = upcoming.get_by_test_id("upcoming-item").count()
        check(items == 3, "立即同步 updated the title, no duplicate")

        feed.status = 500
        page.get_by_role("button", name="立即同步").click()
        page.locator(".badge.status-error").wait_for(timeout=40_000)
        rows = page.get_by_test_id("integrations")
        check("HTTP 500" in rows.inner_text(), "a failing feed shows 出错 with its reason")
        page.get_by_test_id("kind-schedule").get_by_text("同步出错").wait_for(timeout=20_000)
        check(
            "HTTP 500" in page.get_by_test_id("kind-schedule").inner_text(),
            "数据来源总览: 日程 shows 同步出错 with the reason",
        )
        check(feed.token not in page.content(), "the token is not in the error either")
        shot(page, out, "10-error")

        rows.get_by_role("button", name="删除").click()
        confirm = rows.get_by_role("button", name="确定删除（连同已同步的条目和订阅链接）")
        confirm.wait_for()
        check(len(api.get("/integrations").json()) == 1, "a single click on 删除 deletes nothing")
        confirm.click()
        page.get_by_text("还没有连接任何来源").wait_for()
        check(api.get("/integrations").json() == [], "the integration is gone from the Hub")
        check(api.get("/credentials").json() == [], "its credential is gone from the Hub")
        check(keyring.get_password(service, key) is None, "and gone from Credential Manager")
        shot(page, out, "11-disconnected")
        check(not leaks, f"the link travelled only in PUT /credentials ({leaks})")
        hub_text = hub_log.read_text(encoding="utf-8", errors="replace")
        check(feed.token not in hub_text, "the feed token is not in the Hub log")
    finally:
        page.remove_listener("request", watch)
        feed.close()
        if key is not None:  # also when a check above failed
            with contextlib.suppress(Exception):
                keyring.delete_password(service, key)


def verify_canvas_view(
    page: Page, api: httpx.Client, out: Path, service: str, hub_log: Path
) -> None:
    token = f"canvastoken-{uuid.uuid4().hex[:20]}"
    canvas = FakeCanvas(token)
    owner = os.environ.get("POS_OWNER_ID", "local")
    key: str | None = None
    try:
        form = page.get_by_role("form", name="连接 Canvas")
        form.get_by_label("学校的 Canvas 网址").fill(canvas.base)
        form.get_by_label("访问令牌（不会再显示）").fill(token)
        form.get_by_role("button", name="连接 Canvas").click()
        upcoming = page.get_by_test_id("upcoming")
        upcoming.get_by_text(canvas.title).wait_for(timeout=40_000)
        check(True, "Canvas work appears in 接下来 14 天 (incl. yesterday's missing lab)")
        lab = upcoming.get_by_test_id("upcoming-item").filter(has_text=canvas.title)
        check(lab.get_by_text("缺交").count() == 1, "a missing assignment shows 缺交")
        quiz = upcoming.get_by_test_id("upcoming-item").filter(has_text="Quiz 5")
        check(quiz.get_by_text("已提交").count() == 1, "a submitted one shows 已提交")
        news = page.get_by_test_id("news")
        check(news.get_by_text("Midterm moved").count() == 1, "the announcement shows in 最近公告")
        check(token not in page.content(), "the Canvas token is nowhere in the page")
        name = next(
            c["name"] for c in api.get("/credentials").json() if c["name"].startswith("canvas.")
        )
        key = f"{owner}:{name}"
        check(keyring.get_password(service, key) == token, "the token is in Credential Manager")
        shot(page, out, "12-canvas")
        open_view(page, "成绩")
        card = page.get_by_test_id("gpa-course").filter(has_text="CIS D022A")
        card.wait_for(timeout=30_000)
        text = card.inner_text()
        check(
            "93.5" in text and card.locator(".gpa-grade").inner_text() == "A",
            f"成绩 shows the Canvas score and letter ({text[:60]!r})",
        )
        check(card.get_by_test_id("gpa-missing").count() == 1, "and the missing lab")
        # T-0049: a syllabus rules card decides the letter; the user confirms it once.
        profile = {
            "code": "CIS D022A",
            "units": 4.5,
            "units_source": "syllabus",
            "scale": [
                {"letter": "A", "min": 94},
                {"letter": "A-", "min": 90},
                {"letter": "F", "min": 0},
            ],
            "scale_source": "syllabus",
            "rules": [{"kind": "late", "text": "作业不收迟交", "source": "No late work."}],
            "open_questions": ["分数线请向老师确认"],
            "syllabus_source": "verify",
        }
        put = api.put("/academic/profiles/CIS D022A", json={"fields": profile, "version": None})
        check(put.status_code == 200, f"PUT /academic/profiles -> 200 ({put.status_code})")
        open_view(page, "任务")
        open_view(page, "成绩")
        card = page.get_by_test_id("gpa-course").filter(has_text="CIS D022A")
        card.get_by_test_id("rules-card").wait_for(timeout=20_000)
        head = card.locator(".gpa-head").inner_text()
        shown = float(re.search(r"(\d+(?:\.\d+)?)%", head).group(1))  # type: ignore[union-attr]
        expected = "A" if shown >= 94 else "A-" if shown >= 90 else "F"
        check(
            card.locator(".gpa-grade").inner_text() == expected,
            f"the syllabus scale decides the letter ({shown}% is {expected} on it)",
        )
        check("缺交算成 0" in card.inner_text(), "Canvas leaving the missing lab out is said")
        check("Canvas 显示 A" in card.inner_text(), "and the Canvas disagreement is said")
        check("4.5 学分" in card.inner_text(), "the units show")
        rules = card.get_by_test_id("rules-card")
        check(rules.get_by_text("待你确认").count() == 1, "the rules card waits for the user")
        rules.get_by_role("button", name="规则卡", exact=False).click()
        check("No late work." in rules.inner_text(), "each rule shows its syllabus words")
        rules.get_by_role("button", name="我对照过大纲，没问题").click()
        rules.get_by_text("已确认").wait_for(timeout=10_000)
        check(True, "confirming marks it 已确认")
        # T-0050: a course computed from the syllabus's own categories says so, and does
        # not show Canvas's unweighted group table or 按总分计算.
        current = api.get("/academic/profiles/CIS D022A").json()
        profile["categories"] = [{"name": "Labs", "weight": 100, "match": ""}]
        put = api.put(
            "/academic/profiles/CIS D022A",
            json={"fields": profile, "version": current["version"]},
        )
        check(put.status_code == 200, f"the profile takes own categories ({put.status_code})")
        open_view(page, "任务")
        open_view(page, "成绩")
        card = page.get_by_test_id("gpa-course").filter(has_text="CIS D022A")
        card.get_by_text("按大纲的类别加权").wait_for(timeout=20_000)
        text = card.inner_text()
        check(
            "按总分计算" not in text and card.locator(".gpa-groups").count() == 0,
            "a syllabus-computed course hides 按总分计算 and Canvas's group table",
        )
        shot(page, out, "21c-gpa-syllabus")
        card.get_by_text("课件").click()
        check(card.get_by_text("Syllabus.pdf").count() == 1, "and the course materials")
        shot(page, out, "21-gpa")
        page.set_viewport_size({"width": 390, "height": 900})
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        check(not overflow, "成绩 fits a phone screen (no sideways scrolling)")
        shot(page, out, "21b-gpa-phone")
        page.set_viewport_size({"width": 1200, "height": 800})
        open_view(page, "连接")
        page.get_by_test_id("integrations").get_by_text("Canvas").first.wait_for()
        (row,) = [
            r
            for r in page.get_by_test_id("integrations").get_by_role("listitem").all()
            if "Canvas" in r.inner_text()
        ]
        row.get_by_role("button", name="删除").click()
        row.get_by_role("button", name="确定删除（连同已同步的条目和访问令牌）").click()
        page.get_by_text("还没有连接任何来源").wait_for()
        check(keyring.get_password(service, key) is None, "deleting removed the token too")
        hub_text = hub_log.read_text(encoding="utf-8", errors="replace")
        check(token not in hub_text, "the Canvas token is not in the Hub log")
    finally:
        canvas.close()
        if key is not None:
            with contextlib.suppress(Exception):
                keyring.delete_password(service, key)


def verify_email_view(
    page: Page, api: httpx.Client, out: Path, service: str, hub_log: Path
) -> None:
    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    box = Mailbox(username="student@example.com", password=code)
    box.add(fake_mail("作业提醒 Lab 3 明天截止", "请在明天之前提交。"), received=recent(2))
    imap = FakeImapServer(box)
    owner = os.environ.get("POS_OWNER_ID", "local")
    key: str | None = None
    try:
        # The form only offers real servers; the stand-in is local, so it is added through
        # the same API calls the form makes, with the test server's address.
        name = f"mail.{uuid.uuid4().hex[:10]}"
        api.put(f"/credentials/{name}", json={"secret": code, "note": "163"})
        key = f"{owner}:{name}"
        config = {
            "host": "127.0.0.1",
            "port": str(imap.port),
            "username": "student@example.com",
            "tls": "off",
        }
        created = api.post(
            "/integrations",
            json={"kind": "email", "name": "163 邮箱", "credential_name": name, "config": config},
        )
        check(created.status_code == 201, "an email connection was added")
        form = page.get_by_role("form", name="连接邮箱")
        check(
            form.get_by_label("邮箱服务").input_value() == "imap.163.com", "163 is the first preset"
        )
        page.get_by_test_id("mail-moved").wait_for(timeout=40_000)
        check(True, "连接 says the mail was synced and points to the 邮件 page")
        open_view(page, "邮件")
        mail = page.get_by_test_id("mail-view")
        mail.get_by_text("作业提醒 Lab 3 明天截止").wait_for(timeout=40_000)
        check(True, "the mail shows on the 邮件 page")
        check(mail.locator(".badge.unread").count() == 1, "unread mail is marked 未读")
        check(code not in page.content(), "the code is nowhere in the page")
        shot(page, out, "13-email")
        open_view(page, "今日")
        today_mail = page.get_by_test_id("today-mail")
        today_mail.get_by_text("作业提醒 Lab 3 明天截止").wait_for()
        check(True, "今日 lists the unread mail")
        check(
            "1 封未读邮件" in page.get_by_test_id("today-headline").inner_text(),
            "今日 headline counts the unread mail",
        )
        shot(page, out, "14-today")
        open_view(page, "连接")
        page.get_by_test_id("integrations").get_by_text("163 邮箱").wait_for()
        (row,) = [
            r
            for r in page.get_by_test_id("integrations").get_by_role("listitem").all()
            if "163 邮箱" in r.inner_text()
        ]
        row.get_by_role("button", name="删除").click()
        row.get_by_role(
            "button", name="确定删除（只删本系统里的邮件副本和授权码，不会动邮箱里的邮件）"
        ).click()
        page.get_by_text("还没有连接任何来源").wait_for()
        check(keyring.get_password(service, key) is None, "deleting removed the code too")
        check(
            code not in hub_log.read_text(encoding="utf-8", errors="replace"), "code not in Hub log"
        )
    finally:
        imap.close()
        if key is not None:
            with contextlib.suppress(Exception):
                keyring.delete_password(service, key)


def verify_summaries_view(
    page: Page, api: httpx.Client, out: Path, service: str, hub_log: Path, errors: list[str]
) -> None:
    """T-0023: the DeepSeek key form, summaries on 最近邮件 and 今日 (FakeProvider)."""
    from tests.hub.fake_imap import FakeImapServer, Mailbox

    code = f"MAILCODE-{uuid.uuid4().hex[:16]}"
    model_key = f"sk-verify-{uuid.uuid4().hex}"
    box = Mailbox(username="student@example.com", password=code)
    box.add(
        fake_mail("CIS 22A Lab 5 截止提醒", "Lab 5 截止 周五 23:59，请在 Canvas 提交。"),
        received=recent(3),
    )
    # Read already, so the 未读 filter and count have something to leave out.
    box.add(
        fake_mail("网易邮箱验证码", "您的验证码是 482913，10分钟内有效。"),
        seen=True,
        received=recent(2),
    )
    box.add(fake_mail("The Weekly Digest", "Campus news this week."), received=recent(1))
    imap = FakeImapServer(box)
    owner = os.environ.get("POS_OWNER_ID", "local")
    name = f"mail.{uuid.uuid4().hex[:10]}"
    try:
        api.put(f"/credentials/{name}", json={"secret": code, "note": "163"})
        created = api.post(
            "/integrations",
            json={
                "kind": "email",
                "name": "163 邮箱",
                "credential_name": name,
                "config": {
                    "host": "127.0.0.1",
                    "port": str(imap.port),
                    "username": "student@example.com",
                    "tls": "off",
                },
            },
        )
        check(created.status_code == 201, "an email connection for summaries was added")
        open_view(page, "邮件")
        mail = page.get_by_test_id("mail-view")
        mail.get_by_text("CIS 22A Lab 5 截止提醒").wait_for(timeout=40_000)
        check(True, "before any key the subject is shown")
        mail.get_by_text("未发送给 AI（可能含验证码或重置密码）").wait_for(timeout=20_000)
        check(True, "the OTP mail shows 未发送给 AI before any key exists")
        shot(page, out, "15-ai-no-key")
        open_view(page, "连接")
        card = page.get_by_test_id("ai-card")
        card.get_by_text("还没有设置 key").wait_for()
        check(True, "the AI card says no key is set")

        key_field = card.get_by_test_id("ai-key")
        key_field.fill(model_key)
        card.get_by_role("button", name="保存 key").click()
        check(key_field.input_value() == "", "the key field is cleared at once")
        card.get_by_text("已设置 key").wait_for(timeout=40_000)
        card.get_by_text("（2 次）").wait_for(timeout=40_000)  # both valuable mails summarised
        check("本月已用 $" in card.inner_text(), "the card shows this month's spend")
        # page.content() omits live input values; the cleared field above is the real proof.
        check(model_key not in page.content(), "the key is not in the page markup")
        open_view(page, "邮件")
        mail = page.get_by_test_id("mail-view")
        lab = mail.get_by_test_id("mail-line").filter(has_text="（测试摘要）CIS 22A Lab 5")
        lab.wait_for(timeout=40_000)
        check(True, "the list shows the AI title")
        check(
            "截止提醒" not in lab.get_by_test_id("mail-title").inner_text(),
            "the AI title is cut to 20 characters and replaces the subject",
        )
        check(
            lab.get_by_text("重要").count() == 1 and lab.get_by_text("需处理").count() == 1,
            "the Lab mail is marked 重要 and 需处理",
        )
        digest = mail.get_by_test_id("mail-line").filter(has_text="（测试摘要）The Weekly")
        check(digest.count() == 1, "the newsletter is listed with the rest, not collapsed")
        check(digest.get_by_text("次要").count() == 1, "and it is marked 次要")
        lines = mail.get_by_test_id("mail-title").all_inner_texts()
        news = next((i for i, t in enumerate(lines) if "The Weekly" in t), None)
        lab_at = next((i for i, t in enumerate(lines) if "CIS 22A" in t), None)
        check(
            news is not None and lab_at is not None and news < lab_at,
            f"mail is in time order, newest first ({lines})",
        )
        check(
            "共 3 封，未读 2 封" in mail.locator("h2").first.inner_text(),
            "the heading counts every mail and the unread ones",
        )
        mail.get_by_test_id("mail-filter-action").click()
        acting = mail.get_by_test_id("mail-title").all_inner_texts()
        check(
            len(acting) == 1 and "CIS 22A" in acting[0],
            f"需处理 shows only the mail that needs action ({acting})",
        )
        mail.get_by_test_id("mail-filter-unread").click()
        unread = mail.get_by_test_id("mail-title").all_inner_texts()
        check(
            len(unread) == 2 and not any("验证码" in t for t in unread),
            f"未读 shows the two unread mails, not the read one ({unread})",
        )
        mail.get_by_test_id("mail-filter-all").click()
        lab.locator(".mail-head").click()
        detail = lab.get_by_test_id("mail-detail")
        text = detail.inner_text()
        check(
            "要点：" in text and "原文" in text and text.index("要点：") < text.index("原文"),
            "opening a mail shows the points first, then the original",
        )
        shot(page, out, "16-ai-summaries")

        triage = page.get_by_test_id("triage")
        opened = triage.get_by_test_id("triage-open")
        check(
            "未处理 2 封" in opened.inner_text(),
            f"the panel counts open mail ({opened.inner_text()})",
        )
        triage.get_by_test_id("triage-toggle").click()
        news = triage.get_by_test_id("triage-group").filter(has_text="The Weekly")
        check(news.count() == 1, "帮我整理 shows the newsletter in a group")
        news.get_by_test_id("mail-line").locator(".mail-head").click()
        check(news.get_by_test_id("mail-detail").count() == 1, "a mail inside a group opens")
        news.get_by_test_id("mail-original").locator("summary").click()
        body = news.get_by_test_id("mail-body")
        check(
            body.is_visible() and "Campus news" in body.inner_text(),
            "and its original text can be read there",
        )
        news.get_by_test_id("triage-handle").click()
        page.wait_for_function(
            "document.querySelector('[data-testid=triage-open]').innerText.includes('未处理 1 封')"
        )
        check(True, "one click handles the group: 未处理 2 -> 1")
        digest_line = mail.get_by_test_id("mail-line").filter(has_text="（测试摘要）The Weekly")
        check(
            digest_line.get_by_test_id("mail-handled").count() == 1
            and digest_line.locator(".badge.unread").count() == 0,
            "the mail shows 已处理 instead of 未读",
        )
        shot(page, out, "19-triage")
        triage.get_by_test_id("triage-undo").click()
        page.wait_for_function(
            "document.querySelector('[data-testid=triage-open]').innerText.includes('未处理 2 封')"
        )
        check(True, "撤销 puts it back to 2")
        lab.get_by_test_id("mail-toggle-handled").click()
        lab.get_by_test_id("mail-handled").wait_for()
        check(True, "one mail can be marked 已处理 by hand")
        lab.get_by_test_id("mail-toggle-handled").click()
        lab.get_by_test_id("mail-handled").wait_for(state="detached")
        check(True, "and marked back")

        chat = page.get_by_test_id("chat")
        chat.get_by_test_id("chat-input").fill("Lab 5 什么时候交")
        chat.get_by_test_id("chat-send").click()
        answer = chat.get_by_test_id("chat-answer").first
        answer.wait_for(timeout=30_000)
        check("（测试回答）Lab 5 什么时候交" in answer.inner_text(), "the chat box shows an answer")
        cited = chat.get_by_test_id("chat-cited").get_by_test_id("mail-line")
        check(cited.count() >= 1, f"with the mails it used ({cited.count()})")
        cited.first.locator(".mail-head").click()
        check(chat.get_by_test_id("mail-detail").count() == 1, "a cited mail opens like any other")
        shot(page, out, "18-mail-chat")
        chat.get_by_test_id("chat-input").fill("[fake:clear] Lab")
        chat.get_by_test_id("chat-send").click()
        card = chat.get_by_test_id("chat-proposal").last
        card.wait_for(timeout=30_000)
        check(
            "标为已处理" in card.inner_text(),
            f"asked to clear, it proposes ({card.inner_text()[:40]})",
        )
        card.get_by_test_id("chat-confirm").click()
        card.get_by_test_id("chat-done").wait_for()
        check("已处理 1 封" in card.inner_text(), "确认 marks it handled")
        shot(page, out, "20-chat-proposal")
        card.get_by_test_id("chat-undo").click()
        card.get_by_text("已撤销").wait_for()
        check(True, "and 撤销 puts it back")
        chat.get_by_test_id("chat-input").fill("[fake:500] 再问")
        chat.get_by_test_id("chat-send").click()
        chat.get_by_test_id("chat-error").first.wait_for(timeout=30_000)
        check(
            "请再问一次" in chat.get_by_test_id("chat-error").first.inner_text(),
            "a failed answer shows the Hub's sentence",
        )
        # That 502 was asked for ([fake:500]); only it may appear among the console errors.
        expected = [e for e in errors if "/chat/ask" in e or "502 (Bad Gateway)" in e]
        check(len(expected) == 2, f"the asked-for 502 is the only new error ({expected})")
        for line in expected:
            errors.remove(line)

        open_view(page, "今日")
        actions = page.get_by_test_id("today-mail-actions")
        actions.get_by_text("（测试摘要）CIS 22A Lab 5").first.wait_for()
        check(True, "需要处理的邮件 lists the Canvas mail by its AI title")
        check(
            page.get_by_test_id("today-mail").get_by_text("次要").count() == 1,
            "今日 lists the newsletter too, marked 次要",
        )
        check(model_key not in page.content(), "the key is nowhere on 今日 either")
        shot(page, out, "17-today-ai")
        log = hub_log.read_text(encoding="utf-8", errors="replace")
        check(model_key not in log and "482913" not in log, "neither key nor OTP in the Hub log")
    finally:
        imap.close()
        for iid in [i["id"] for i in api.get("/integrations").json() if i["name"] == "163 邮箱"]:
            api.delete(f"/integrations/{iid}")
        for cred in (name, "deepseek"):
            with contextlib.suppress(Exception):
                keyring.delete_password(service, f"{owner}:{cred}")


def verify_schedule_view(page: Page, out: Path) -> None:
    """T-0043: add a weekly class and a clashing workout on 日程, see both, then delete."""
    open_view(page, "日程")
    view = page.get_by_test_id("schedule")
    view.get_by_test_id("sched-add").click()
    form = page.get_by_role("form", name="添加日程")
    now = datetime.now()
    day = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if day.weekday() == 6:  # a Sunday: use the Saturday before, still this Monday-first week
        day -= timedelta(days=1)
    code = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][day.weekday()]
    form.get_by_label("名称").fill("CIS 22A 上课")
    form.get_by_label("类型").select_option("class")
    form.get_by_label("开始").fill(day.strftime("%Y-%m-%dT%H:%M"))
    form.get_by_label("结束").fill((day + timedelta(minutes=110)).strftime("%Y-%m-%dT%H:%M"))
    form.get_by_label(f"周{'一二三四五六日'[day.weekday()]}").check()
    form.get_by_role("button", name="保存").click()
    view.get_by_text("CIS 22A 上课").first.wait_for(timeout=20_000)
    check(True, f"a weekly class shows on 日程 ({code})")
    view.get_by_test_id("sched-add").click()
    form = page.get_by_role("form", name="添加日程")
    form.get_by_label("名称").fill("健身")
    form.get_by_label("类型").select_option("workout")
    clash = day + timedelta(minutes=60)
    form.get_by_label("开始").fill(clash.strftime("%Y-%m-%dT%H:%M"))
    form.get_by_label("结束").fill((clash + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M"))
    form.get_by_role("button", name="保存").click()
    view.get_by_text("健身").first.wait_for(timeout=20_000)
    check(view.get_by_test_id("sched-conflict").count() == 2, "the clash is marked on both")
    check(view.get_by_text("空闲：").count() >= 1, "free time is listed")
    shot(page, out, "22-schedule")
    workout = view.get_by_test_id("sched-entry").filter(has_text="健身").first
    workout.get_by_role("button", name="删除").click()
    view.get_by_test_id("sched-entry").filter(has_text="健身").first.wait_for(state="detached")
    # The class repeats on one weekday: it shows once this week, but deleting it deletes
    # every week, so the button says 删除全部 and asks first.
    asked: list[str] = []

    def accept(d: Dialog) -> None:
        asked.append(d.message)
        d.accept()

    page.once("dialog", accept)
    weekly = view.get_by_test_id("sched-entry").filter(has_text="CIS 22A 上课").first
    weekly.get_by_role("button", name="删除全部").click()
    view.get_by_test_id("sched-entry").filter(has_text="CIS 22A").first.wait_for(state="detached")
    check(bool(asked) and "每周重复" in asked[0], f"a weekly series asks before deleting ({asked})")
    check(view.get_by_test_id("sched-entry").count() == 0, "both are deleted again")


def verify_digest_view(page: Page, out: Path) -> None:
    """T-0044: add a group-chat tip to 简报, open it (read), see the original, today count."""
    open_view(page, "简报")
    view = page.get_by_test_id("digest")
    view.get_by_test_id("digest-add").click()
    form = page.get_by_role("form", name="添加简报")
    form.get_by_label("类别").select_option("group")
    form.get_by_label("来源").fill("微信转学群")
    form.get_by_label("标题").fill("UC 转学：先查 ASSIST 课程对应")
    form.get_by_label("要点").fill("· ASSIST 查课程对应\n· 11/30 截止")
    form.get_by_label("原文").fill("A：转学先看 ASSIST\nB：对，11/30 截止")
    form.get_by_role("button", name="保存").click()
    item = view.get_by_test_id("digest-item").filter(has_text="UC 转学")
    item.wait_for(timeout=20_000)
    check(item.locator(".badge.unread").count() == 1, "a new tip is 未读 in 今天")
    check(
        "未读 1" in view.get_by_role("button", name="今天", exact=False).first.inner_text(),
        "and the 今天 tab counts it",
    )
    item.locator(".mail-head").click()
    item.get_by_test_id("digest-detail").wait_for()
    page.wait_for_function(
        "!document.querySelector('[data-testid=digest-item] .badge.unread')", timeout=10_000
    )
    check(True, "opening it marks it read")
    check("ASSIST 查课程对应" in item.inner_text(), "the points show first")
    shot(page, out, "23-digest")
    page.set_viewport_size({"width": 390, "height": 900})
    wide = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    check(not wide, "简报 fits a phone screen (no sideways scrolling)")
    shot(page, out, "23b-digest-phone")
    page.set_viewport_size({"width": 1200, "height": 800})


def verify_data_kinds(page: Page, out: Path) -> None:
    """T-0046: 连接 starts with the six data kinds and each one's status."""
    open_view(page, "连接")
    overview = page.get_by_test_id("data-kinds")
    overview.wait_for(timeout=20_000)
    keys = ("academic", "schedule", "mail", "pc", "files", "goals")
    check(
        all(overview.get_by_test_id(f"kind-{k}").count() == 1 for k in keys),
        "连接 shows the six data kinds",
    )
    check("以后接入" in overview.get_by_test_id("kind-pc").inner_text(), "PC activity says later")
    check(
        "手动记录" in overview.get_by_test_id("kind-goals").inner_text(),
        "goals are kept in the Hub",
    )
    page.set_viewport_size({"width": 390, "height": 900})
    wide = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    check(not wide, "the overview fits a phone screen")
    shot(page, out, "24-data-kinds-phone")
    # T-0050: on a phone the sidebar is a sticky strip that scrolls sideways; its last item
    # must still be reachable, and the top of the page is what a phone shows first.
    nav = page.get_by_role("navigation", name="切换页面")
    last = nav.get_by_role("button", name="连接")
    last.scroll_into_view_if_needed()
    check(last.is_visible(), "the last nav item (连接) can be reached on a phone")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(out / "25-phone-top.png"), full_page=False)
    check(True, "screenshot 25-phone-top (viewport only)")
    page.set_viewport_size({"width": 1200, "height": 800})


def open_view(page: Page, name: str) -> None:
    page.get_by_role("navigation", name="切换页面").get_by_role("button", name=name).click()


def verify_today_empty(page: Page, out: Path) -> None:
    nav = page.get_by_role("navigation", name="切换页面")
    check(
        nav.get_by_role("button", name="今日").get_attribute("aria-current") == "page",
        "今日 is the page that opens first",
    )
    page.get_by_test_id("today-headline").wait_for()
    check(
        "今天没有截止、日程或未读邮件" in page.get_by_test_id("today-headline").inner_text(),
        "an empty day says so plainly",
    )
    check(page.get_by_text("还没有连接任何来源").count() == 1, "it says nothing is connected yet")
    shot(page, out, "00-today-empty")


def run(out: Path, headed: bool) -> None:
    build_web()
    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    # Feed links go to a throwaway Credential Manager service, removed at the end.
    service = f"personal-os-verify-{uuid.uuid4().hex[:12]}"
    os.environ["POS_CREDENTIALS_SERVICE"] = service
    os.environ["POS_MODEL_PROVIDER"] = "fake"  # summaries without a real model (ADR 0027)
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
            verify_today_empty(page, out)
            open_view(page, "任务")
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
            open_view(page, "任务")
            row.locator(".badge.done").wait_for()
            check(
                row.get_by_test_id("task-status").inner_text() == "已完成",
                "still 已完成 after reloading the page",
            )
            verify_memory_view(page, api, out, errors)
            hub_log = Path(tmp) / "hub-data.log"  # where running_hub writes the Hub's log
            verify_connections_view(page, api, out, errors, service, hub_log)
            verify_canvas_view(page, api, out, service, hub_log)
            verify_email_view(page, api, out, service, hub_log)
            verify_summaries_view(page, api, out, service, hub_log, errors)
            verify_schedule_view(page, out)
            verify_digest_view(page, out)
            verify_data_kinds(page, out)
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
    finally:
        os.environ.pop("POS_CREDENTIALS_SERVICE", None)
    print("\nRESULT: PASS (web)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
