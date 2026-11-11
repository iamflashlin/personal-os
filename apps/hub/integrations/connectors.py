"""Connectors fetch from one kind of source. They never see the database (ADR 0019)."""

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from apps.hub.integrations import ics

MAX_FEED_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 20  # per socket operation
DEADLINE_S = 60  # for the whole download: the one job worker must not stall


class SyncError(Exception):
    """A fetch failed. The message is safe to store: it never contains the secret URL."""


@dataclass(frozen=True)
class ItemIn:
    item_type: str
    external_id: str
    title: str
    body: str = ""
    location: str = ""
    url: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool = False
    data: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class Batch:
    items: list[ItemIn] | None  # None: the source reports nothing changed
    cursor: dict[str, Any]
    # True only if `items` is everything the source has: then stored items that are not in
    # it were deleted at the source and are removed here too (ADR 0019 §2).
    complete: bool = False


class Connector(Protocol):
    def fetch(self, secret: str, cursor: Mapping[str, Any], config: Mapping[str, Any]) -> Batch: ...


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https"):
            raise SyncError("the feed redirected to an unsupported address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


def _external_id(uid: str) -> str:
    """Long UIDs are hashed, so two that differ after 500 characters stay two items."""
    if len(uid) <= 500:
        return uid
    return "sha256:" + hashlib.sha256(uid.encode("utf-8")).hexdigest()


class IcsConnector:
    """A calendar feed whose URL is the secret (Canvas, Google, Outlook all offer one).

    Every error names only a status or an exception type, never the URL: Canvas puts its
    private token in the path, where no redaction pattern would find it.
    """

    def fetch(self, secret: str, cursor: Mapping[str, Any], config: Mapping[str, Any]) -> Batch:
        url = secret.strip()
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise SyncError("the feed address must start with http:// or https://")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            raise SyncError("the feed address contains spaces or line breaks; paste it again")
        headers = {"User-Agent": "personal-os-hub", "Accept": "text/calendar"}
        if cursor.get("etag"):
            headers["If-None-Match"] = str(cursor["etag"])
        if cursor.get("last_modified"):
            headers["If-Modified-Since"] = str(cursor["last_modified"])
        deadline = time.monotonic() + DEADLINE_S
        try:
            request = urllib.request.Request(url, headers=headers)
            with _OPENER.open(request, timeout=TIMEOUT_S) as response:
                chunks: list[bytes] = []
                size = 0
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_FEED_BYTES:
                        raise SyncError("the feed is larger than 5 MB")
                    if time.monotonic() > deadline:
                        raise SyncError(f"the feed took longer than {DEADLINE_S} s")
                    chunks.append(chunk)
                etag = response.headers.get("ETag")
                modified = response.headers.get("Last-Modified")
        except SyncError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return Batch(items=None, cursor=dict(cursor))
            raise SyncError(f"the feed answered HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            raise SyncError(f"the feed could not be reached ({type(reason).__name__})") from None
        except Exception as exc:  # e.g. http.client.InvalidURL, whose message holds the URL
            raise SyncError(f"the feed could not be fetched ({type(exc).__name__})") from None
        try:
            events, ended = ics.parse_feed(b"".join(chunks).decode("utf-8-sig", errors="replace"))
        except ics.NotACalendar as exc:
            raise SyncError(str(exc)) from None
        items = [
            ItemIn(
                item_type="calendar_event",
                external_id=_external_id(e.uid),
                title=e.summary,
                body=e.description,
                location=e.location,
                url=e.url,
                starts_at=e.starts_at,
                ends_at=e.ends_at,
                all_day=e.all_day,
                data=dict(e.flags),
            )
            for e in events
        ]
        new_cursor = {k: v for k, v in (("etag", etag), ("last_modified", modified)) if v}
        # A feed cut off mid-download is used, but cannot say what was deleted.
        return Batch(items=items, cursor=new_cursor, complete=ended)
