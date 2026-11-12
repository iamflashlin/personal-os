"""Canvas LMS through its REST API (ADR 0020, ADR 0037).

Reads active courses with their current score and assignment groups (weights), their
assignments (due date, points, group, submission state and score), the course materials
listed in modules (files, pages, links: names and Canvas links only, nothing downloaded)
and recent announcements, with a personal access token the user created in Canvas. The token goes
only to the configured Canvas origin (scheme, host and port): every request, every
`Link: rel="next"` page and every redirect is checked against it, because urllib would
otherwise carry the Authorization header along, even over plain http.
"""

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.hub.integrations.connectors import Batch, ItemIn, SyncError

TIMEOUT_S = 20
DEADLINE_S = 120
MAX_PAGES = 20  # per list: 20 pages of 100 is far more than one student's courses
MAX_PAGE_BYTES = 10 * 1024 * 1024
MAX_BODY = 2000
ANNOUNCEMENT_DAYS = 30
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_PORT = {"https": 443, "http": 80}


def _origin(url: str) -> tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or _DEFAULT_PORT.get(scheme, 0)


def canvas_base_url(raw: str) -> str:
    """The Canvas address as scheme://host[:port]. https, or http only on this PC.
    No user name or password in it: config is not secret and is shown and audited."""
    parts = urllib.parse.urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not host or scheme not in ("https", "http"):
        raise ValueError("the Canvas address must look like https://school.instructure.com")
    if parts.username or parts.password:
        raise ValueError("the Canvas address must not contain a user name or password")
    if scheme == "http" and host not in _LOOPBACK:
        raise ValueError("the Canvas address must use https")
    port = parts.port
    shown = host if port in (None, _DEFAULT_PORT[scheme]) else f"{host}:{port}"
    return f"{scheme}://{shown}"


class _SameOriginOnly(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        self.origin = origin

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if _origin(newurl) != self.origin:
            raise SyncError("Canvas redirected elsewhere; the token was not sent there")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_DROP = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_BLOCK_TAG = re.compile(r"</?(?:p|br|div|li|ul|ol|h[1-6]|tr|td|table|blockquote)\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Plain text: block tags separate words, inline tags (<b>, <a>) just disappear."""
    kept = _DROP.sub(" ", text or "")
    spaced = _BLOCK_TAG.sub(" ", kept)
    plain = html.unescape(_ANY_TAG.sub("", spaced))
    return re.sub(r"\s+", " ", plain).strip()[:MAX_BODY]


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


_LINK = re.compile(r'<([^>]*)>\s*;[^,]*?\brel="?next"?', re.I)


def _next_link(header: str | None, current: str) -> str | None:
    match = _LINK.search(header or "")
    return urllib.parse.urljoin(current, match.group(1)) if match else None


def _id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Missing(SyncError):
    """HTTP 404. For an optional list (groups, modules) it means "none", not a failure."""


class _Denied(Exception):
    """Canvas refused one resource (e.g. a course whose assignments are hidden)."""


class _Client:
    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.origin = _origin(base)
        self.token = token
        self.opener = urllib.request.build_opener(_SameOriginOnly(self.origin))
        self.deadline = time.monotonic() + DEADLINE_S

    def pages(self, path: str, params: Mapping[str, Any]) -> Iterator[Any]:
        url: str | None = f"{self.base}{path}?{urllib.parse.urlencode(params, doseq=True)}"
        for _ in range(MAX_PAGES):
            if url is None:
                return
            if _origin(url) != self.origin:
                raise SyncError("Canvas pointed elsewhere; the token was not sent there")
            if time.monotonic() > self.deadline:
                raise SyncError(f"Canvas took longer than {DEADLINE_S} s")
            body, link = self._get(url)
            if not isinstance(body, list):
                # An error envelope or a maintenance page; reading it as "nothing here"
                # would let a complete sync delete everything in that list.
                raise SyncError("Canvas answered with something other than a list")
            yield from body
            url = _next_link(link, url)
        if url is not None:
            raise SyncError(f"Canvas returned more than {MAX_PAGES} pages for one list")

    def _get(self, url: str) -> tuple[Any, str | None]:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "personal-os-hub",
            },
        )
        try:
            with self.opener.open(request, timeout=TIMEOUT_S) as response:
                raw = response.read(MAX_PAGE_BYTES + 1)
                link = response.headers.get("Link")
        except SyncError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise _Denied(exc.code) from None
            if exc.code == 404:
                raise _Missing("Canvas answered HTTP 404") from None
            raise SyncError(f"Canvas answered HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise SyncError(f"Canvas could not be reached ({type(exc.reason).__name__})") from None
        except Exception as exc:  # never let a message that may quote the URL through
            raise SyncError(f"Canvas could not be fetched ({type(exc).__name__})") from None
        if len(raw) > MAX_PAGE_BYTES:
            raise SyncError("a Canvas page was larger than 10 MB")
        try:
            return json.loads(raw), link
        except ValueError:
            raise SyncError("Canvas did not answer with JSON") from None


def _course_label(course: Mapping[str, Any]) -> str:
    return str(course.get("name") or course.get("course_code") or "")


MATERIAL_TYPES = {"File", "Page", "ExternalUrl", "ExternalTool"}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _course(course: Mapping[str, Any], groups: list[Mapping[str, Any]]) -> ItemIn:
    """The course itself: its current grade as Canvas computes it, and its groups."""
    enrollments = course.get("enrollments")
    first = enrollments[0] if isinstance(enrollments, list) and enrollments else {}
    enrollment: Mapping[str, Any] = first if isinstance(first, dict) else {}
    data: dict[str, Any] = {
        "course_code": str(course.get("course_code") or ""),
        # Canvas's "current" score counts only graded work; its "final" score counts every
        # ungraded assignment as 0, so it is far below what the student has earned so far.
        "current_score": _number(enrollment.get("computed_current_score")),
        "current_grade": str(enrollment.get("computed_current_grade") or ""),
        "final_score": _number(enrollment.get("computed_final_score")),
        "weighted": bool(course.get("apply_assignment_group_weights")),
        "groups": [
            {
                "id": _id(g.get("id")),
                "name": str(g.get("name") or "").strip(),
                "weight": _number(g.get("group_weight")) or 0.0,
            }
            for g in groups
            if _id(g.get("id")) is not None
        ],
    }
    return ItemIn(
        item_type="canvas_course",
        external_id=str(course["id"]),
        title=_course_label(course),
        url=f"{course.get('_base', '')}/courses/{course['id']}",
        data=data,
    )


def _material(course: Mapping[str, Any], module: Mapping[str, Any], m: Mapping[str, Any]) -> ItemIn:
    return ItemIn(
        item_type="canvas_material",
        external_id=f"{course['id']}:{m['id']}",
        title=str(m.get("title") or ""),
        url=str(m.get("html_url") or ""),
        data={
            "course": _course_label(course),
            "course_code": str(course.get("course_code") or ""),
            "module": str(module.get("name") or "").strip(),
            "module_position": module.get("position"),
            "kind": str(m.get("type") or ""),
            "position": m.get("position"),
        },
    )


def _assignment(course: Mapping[str, Any], a: Mapping[str, Any]) -> ItemIn:
    raw_submission = a.get("submission")
    submission: Mapping[str, Any] = raw_submission if isinstance(raw_submission, dict) else {}
    data: dict[str, Any] = {
        "course": _course_label(course),
        "course_code": str(course.get("course_code") or ""),
        "points_possible": a.get("points_possible"),
        "submission_state": str(submission.get("workflow_state") or ""),
        "submitted_at": submission.get("submitted_at"),
        "score": submission.get("score"),
        "grade": str(submission.get("grade") or ""),
        "graded_at": submission.get("graded_at"),
        "excused": bool(submission.get("excused")),
        "missing": bool(submission.get("missing")),
        "late": bool(submission.get("late")),
        "group_id": _id(a.get("assignment_group_id")),
        "omit_from_final": bool(a.get("omit_from_final_grade")),
    }
    return ItemIn(
        item_type="canvas_assignment",
        external_id=f"{course['id']}:{a['id']}",
        title=str(a.get("name") or ""),
        url=str(a.get("html_url") or ""),
        starts_at=_when(a.get("due_at")),
        data=data,
    )


def _announcement(course: Mapping[str, Any], n: Mapping[str, Any]) -> ItemIn:
    return ItemIn(
        item_type="canvas_announcement",
        external_id=str(n["id"]),
        title=str(n.get("title") or ""),
        body=_strip_html(str(n.get("message") or "")),
        url=str(n.get("html_url") or ""),
        starts_at=_when(n.get("posted_at")),
        data={"course": _course_label(course)},
    )


class CanvasConnector:
    def fetch(self, secret: str, cursor: Mapping[str, Any], config: Mapping[str, Any]) -> Batch:
        try:
            base = canvas_base_url(str(config.get("base_url", "")))
        except ValueError as exc:
            raise SyncError(str(exc)) from None
        client = _Client(base, secret.strip())
        try:
            listed = list(
                client.pages(
                    "/api/v1/courses",
                    {"enrollment_state": "active", "per_page": 100, "include[]": "total_scores"},
                )
            )
        except _Denied as denied:
            # Refusing the course list itself means the token is not accepted.
            raise SyncError(
                f"Canvas refused the token (HTTP {denied}); create a new one in Canvas"
            ) from None
        courses: list[dict[str, Any]] = []
        for c in listed:
            course_id = _id(c.get("id")) if isinstance(c, dict) else None
            if course_id is not None and _course_label(c):
                courses.append({**c, "id": course_id})

        items: list[ItemIn] = []
        skipped = 0
        for course in courses:
            course["_base"] = base
            try:
                groups = [
                    g
                    for g in client.pages(
                        f"/api/v1/courses/{course['id']}/assignment_groups", {"per_page": 100}
                    )
                    if isinstance(g, dict)
                ]
                items.append(_course(course, groups))
            except _Missing:
                items.append(_course(course, []))
            except _Denied:
                skipped += 1
            try:
                for module in client.pages(
                    f"/api/v1/courses/{course['id']}/modules",
                    {"include[]": "items", "per_page": 100},
                ):
                    if not isinstance(module, dict):
                        continue
                    for m in module.get("items") or []:
                        if (
                            isinstance(m, dict)
                            and m.get("type") in MATERIAL_TYPES
                            and _id(m.get("id")) is not None
                        ):
                            items.append(_material(course, module, m))
            except _Missing:
                pass  # no modules in this course
            except _Denied:
                skipped += 1  # modules can be hidden from students
            try:
                for a in client.pages(
                    f"/api/v1/courses/{course['id']}/assignments",
                    {"include[]": "submission", "per_page": 100, "order_by": "due_at"},
                ):
                    if isinstance(a, dict) and _id(a.get("id")) is not None:
                        items.append(_assignment(course, a))
            except _Denied:
                skipped += 1  # e.g. a hidden assignments tab: the other courses still sync
        if courses:
            now = datetime.now(UTC)
            by_code = {f"course_{c['id']}": c for c in courses}
            params = {
                "context_codes[]": list(by_code),
                "start_date": (now - timedelta(days=ANNOUNCEMENT_DAYS)).date().isoformat(),
                # Canvas ends the window 28 days after start_date unless told otherwise.
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "per_page": 100,
            }
            try:
                for n in client.pages("/api/v1/announcements", params):
                    if isinstance(n, dict) and n.get("id") is not None:
                        course = by_code.get(str(n.get("context_code")), {})
                        items.append(_announcement(course, n))
            except _Denied:
                skipped += 1
        # A skipped course means its assignments are unknown, not deleted: no pruning then.
        return Batch(
            items=items, cursor={**cursor, "skipped_resources": skipped}, complete=skipped == 0
        )
