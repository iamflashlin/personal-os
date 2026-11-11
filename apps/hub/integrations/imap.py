# ruff: noqa: RUF001  (Chinese placeholder subjects use full-width brackets on purpose)
"""Email over IMAP, read-only (ADR 0022).

Works with NetEase 163 (IMAP with a client authorisation code, and the IMAP `ID` command
NetEase requires before a mailbox can be opened) and with Gmail or any IMAP server. The
mailbox is opened read-only and messages are fetched with BODY.PEEK, so nothing is marked
as read and nothing is ever changed on the server.

No mail is skipped silently: new mail is read oldest first and the cursor only moves past
a message once it is stored (a too-large or unreadable one is stored as a short note).
"""

import contextlib
import email
import email.policy
import html
import imaplib
import re
import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from apps.hub.integrations.connectors import Batch, ItemIn, SyncError

TIMEOUT_S = 30
DEADLINE_S = 180
FIRST_SYNC_DAYS = 14
MAX_PER_SYNC = 200
MAX_MESSAGE_BYTES = 5 * 1024 * 1024
PARTIAL_TEXT_BYTES = 65536
MAX_HTML_CHARS = 200_000
MAX_BODY = 8000
RECENT_DAYS = 7  # read state is refreshed for mail received this recently
MAX_RECENT = 300
MAX_TRIES = 3  # syncs that may fail on one message before it is stored as a note
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
# Printable ASCII without quotes, backslashes or spaces: IMAP LOGIN takes it unquoted.
_ADDRESS = re.compile(r"^[!#-\[\]-~]{1,128}@[A-Za-z0-9.-]{1,253}$")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_GB2312 = re.compile(rb"(?i)(charset=\"?|=\?)gb2312")

# NetEase rejects SELECT ("Unsafe Login") from clients that did not identify themselves.
imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))


def check_imap_config(config: Mapping[str, str]) -> dict[str, str]:
    """Normalised IMAP settings; ValueError if wrong. None of them is secret."""
    unknown = set(config) - {"host", "port", "username", "folder", "tls"}
    if unknown:
        raise ValueError(f"unknown email settings: {sorted(unknown)}")
    host = config.get("host", "").strip().lower()
    if not _HOST.fullmatch(host):
        raise ValueError("the mail server must look like imap.163.com")
    username = config.get("username", "").strip()
    if not _ADDRESS.fullmatch(username):
        raise ValueError("the email address must look like name@163.com")
    tls = config.get("tls", "on")
    if tls not in ("on", "off") or (tls == "off" and host not in _LOOPBACK):
        raise ValueError("email must use TLS (tls=off only on this PC, for tests)")
    try:
        port = int(config.get("port", "993" if tls == "on" else "143"))
    except ValueError:
        raise ValueError("the port must be a number") from None
    if not 1 <= port <= 65535:
        raise ValueError("the port must be between 1 and 65535")
    folder = config.get("folder", "INBOX").strip() or "INBOX"
    if not folder.isascii() or any(c in folder for c in '"\r\n\\') or len(folder) > 100:
        raise ValueError("the folder name must be plain ASCII without quotes")
    return {"host": host, "port": str(port), "username": username, "folder": folder, "tls": tls}


def _clean(value: Any) -> str:
    """Text safe to store: undecodable bytes (lone surrogates) become U+FFFD."""
    text = str(value or "")
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _decode(value: Any) -> str:
    return _clean(value).replace("\r", " ").replace("\n", " ").strip()


def _text_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = str(part.get_content())
    except (LookupError, ValueError, AttributeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""
    content = _clean(content)
    if part.get_content_subtype() == "html":
        content = content[:MAX_HTML_CHARS]  # only MAX_BODY characters are kept anyway
        content = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", content, flags=re.I | re.S)
        content = html.unescape(re.sub(r"<[^>]+>", " ", content))
    return re.sub(r"\s+", " ", content).strip()[:MAX_BODY]


@dataclass(frozen=True)
class _Meta:
    uid: int
    seen: bool
    size: int  # -1 when the server did not say
    received: datetime | None


def _received(text: str) -> datetime | None:
    match = re.search(r'INTERNALDATE "([^"]+)"', text)
    if not match:
        return None
    parsed = imaplib.Internaldate2tuple(f'INTERNALDATE "{match.group(1)}"'.encode())
    if parsed is None:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), UTC)


def _metas(data: list[Any]) -> dict[int, _Meta]:
    found: dict[int, _Meta] = {}
    for part in data:
        head = part[0] if isinstance(part, tuple) else part
        text = head.decode(errors="replace") if isinstance(head, bytes) else str(head or "")
        uid = re.search(r"UID (\d+)", text)
        if not uid:
            continue
        flags = re.search(r"FLAGS \(([^)]*)\)", text)
        size = re.search(r"RFC822\.SIZE (\d+)", text)
        found[int(uid.group(1))] = _Meta(
            uid=int(uid.group(1)),
            seen="\\Seen" in (flags.group(1) if flags else ""),
            size=int(size.group(1)) if size else -1,
            received=_received(text),
        )
    return found


def _literals(data: list[Any]) -> list[bytes]:
    return [p[1] for p in data if isinstance(p, tuple) and len(p) == 2 and isinstance(p[1], bytes)]


def _external_id(msg: EmailMessage, uidvalidity: str, meta: _Meta) -> str:
    """Survives a renumbered folder. The sender picks the Message-ID, so it is paired with
    the server's receive time (or size): a second mail reusing it never replaces the first."""
    message_id = _decode(msg.get("Message-ID"))
    if message_id and len(message_id) <= 300:
        stamp = meta.received.isoformat() if meta.received else str(meta.size)
        return f"mid:{message_id}|{stamp}"
    return f"uid:{uidvalidity}:{meta.uid}"


def _parse(raw: bytes) -> EmailMessage:
    # Chinese mail often labels GBK text as gb2312; gb18030 is a superset that reads both.
    msg = email.message_from_bytes(_GB2312.sub(rb"\1gb18030", raw), policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    return msg


def _item(uidvalidity: str, meta: _Meta, raw: bytes, note: str = "") -> ItemIn:
    msg = _parse(raw)
    senders = getaddresses([_clean(msg.get("From", ""))])
    name, address = senders[0] if senders else ("", "")
    try:
        sent = parsedate_to_datetime(_clean(msg.get("Date", "")))
        # "-0000" means "zone unknown": parsed naive, it must not be read as Hub local time.
        sent = sent.replace(tzinfo=UTC) if sent.tzinfo is None else sent.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        sent = None
    attachments = [_decode(p.get_filename()) for p in msg.iter_attachments() if p.get_filename()]
    data: dict[str, Any] = {
        "from_name": _decode(name),
        "from_address": _decode(address),
        "to": _decode(msg.get("To"))[:500],
        "seen": meta.seen,
        "attachments": [a[:200] for a in attachments][:20],
        "message_id": _decode(msg.get("Message-ID"))[:300],
        "uid": meta.uid,
        "size": meta.size,
        "sent_at": sent.isoformat() if sent else None,
    }
    if note:
        data["note"] = note
    body = _text_of(msg)
    return ItemIn(
        item_type="email_message",
        external_id=_external_id(msg, uidvalidity, meta),
        title=_decode(msg.get("Subject")) or "（无主题）",
        body=f"{note} {body}".strip() if note else body,
        # The server's receive time: always present, and not chosen by the sender.
        starts_at=meta.received or sent,
        data=data,
    )


def _unreadable(uidvalidity: str, meta: _Meta, reason: str) -> ItemIn:
    return ItemIn(
        item_type="email_message",
        external_id=f"uid:{uidvalidity}:{meta.uid}",
        title="（无法解析的邮件）",
        body=f"这封邮件读取失败（{reason}），请在邮箱里查看。",
        starts_at=meta.received,
        data={"seen": meta.seen, "uid": meta.uid, "size": meta.size, "note": reason},
    )


def _still_recent(entries: Any, since: datetime) -> list[list[Any]]:
    """Cursor entries [uid, external_id, received] for mail received after `since`."""
    kept: list[list[Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            uid, ext, received = entry
            if datetime.fromisoformat(str(received)) >= since:
                kept.append([int(uid), str(ext), str(received)])
        except (TypeError, ValueError):
            continue  # an older or damaged entry: drop it
    return kept


def _since(day: datetime) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


class ImapConnector:
    def fetch(self, secret: str, cursor: Mapping[str, Any], config: Mapping[str, Any]) -> Batch:
        try:
            settings = check_imap_config({k: str(v) for k, v in config.items()})
        except ValueError as exc:
            raise SyncError(str(exc)) from None
        code = secret.strip()
        if not code.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in code):
            raise SyncError("the 授权码 contains unusual characters; paste it again")
        deadline = time.monotonic() + DEADLINE_S
        try:
            conn = self._connect(settings)
        except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
            reason = type(exc).__name__
            raise SyncError(f"the mail server could not be reached ({reason})") from None
        try:
            return self._read(conn, settings, code, cursor, deadline)
        finally:
            with contextlib.suppress(OSError, imaplib.IMAP4.error):
                conn.logout()

    def _connect(self, s: Mapping[str, str]) -> imaplib.IMAP4:
        if s["tls"] == "on":
            context = ssl.create_default_context()
            return imaplib.IMAP4_SSL(
                s["host"], int(s["port"]), ssl_context=context, timeout=TIMEOUT_S
            )
        return imaplib.IMAP4(s["host"], int(s["port"]), timeout=TIMEOUT_S)

    def _login(self, conn: imaplib.IMAP4, s: Mapping[str, str], code: str) -> None:
        try:
            conn.login(s["username"], code)
        except imaplib.IMAP4.abort:
            raise SyncError("the connection to the mail server dropped during login") from None
        except imaplib.IMAP4.error:
            raise SyncError(
                "the mail server refused the login: for 163, turn on IMAP in the mail "
                "settings and use the 授权码, not the password"
            ) from None
        # Tell the server who we are (NetEase requires it); servers without ID refuse it.
        with contextlib.suppress(imaplib.IMAP4.error):
            conn._simple_command("ID", '("name" "personal-os" "version" "0.1")')

    def _read(
        self,
        conn: imaplib.IMAP4,
        s: Mapping[str, str],
        code: str,
        cursor: Mapping[str, Any],
        deadline: float,
    ) -> Batch:
        self._login(conn, s, code)
        try:
            status, _ = conn.select(f'"{s["folder"]}"', readonly=True)
        except imaplib.IMAP4.error:
            status = "NO"
        if status != "OK":
            raise SyncError(f"the mail server would not open the folder {s['folder']}")
        uidvalidity = self._uidvalidity(conn)
        renumbered = str(cursor.get("uidvalidity", "")) != uidvalidity
        last_uid = 0 if renumbered else int(cursor.get("last_uid", 0) or 0)
        recent_since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
        recent = [] if renumbered else _still_recent(cursor.get("recent", []), recent_since)
        stuck: dict[str, int] = {} if renumbered else dict(cursor.get("stuck") or {})

        if last_uid:
            criteria = f"UID {last_uid + 1}:*"
        else:
            criteria = f"SINCE {_since(datetime.now(UTC) - timedelta(days=FIRST_SYNC_DAYS))}"
        status, found = conn.uid("SEARCH", criteria)
        if status != "OK":
            raise SyncError("the mail server refused the search")
        words = b" ".join(f for f in found if isinstance(f, bytes)).split()
        # Oldest first: what does not fit in this sync is read by the next one.
        uids = sorted({int(u) for u in words if u.isdigit() and int(u) > last_uid})
        uids = uids[:MAX_PER_SYNC]

        items: list[ItemIn] = []
        newest = last_uid
        if uids:
            status, data = conn.uid(
                "FETCH", ",".join(map(str, uids)), "(FLAGS RFC822.SIZE INTERNALDATE)"
            )
            metas = _metas(data) if status == "OK" else {}
            for uid in uids:
                if time.monotonic() > deadline or uid not in metas:
                    break  # the cursor stays before it: the next sync tries again
                lost = False
                try:
                    item = self._message(conn, uidvalidity, metas[uid])
                except (OSError, imaplib.IMAP4.error):
                    item, lost = None, True
                if item is None:
                    # Refused or timed out: retry next sync, but never block the mailbox for
                    # good. After MAX_TRIES syncs on the same message it becomes a note.
                    tries = stuck.get("tries", 0) + 1 if stuck.get("uid") == uid else 1
                    if tries < MAX_TRIES:
                        stuck = {"uid": uid, "tries": tries}
                        break
                    item = _unreadable(uidvalidity, metas[uid], "the server refused it")
                stuck = {}
                items.append(item)
                newest = uid
                received = metas[uid].received
                if received and received >= recent_since:
                    recent.append([uid, item.external_id, received.isoformat()])
                if lost:
                    break  # the connection may be gone: stop with what was read

        recent = recent[-MAX_RECENT:]
        patches, recent = self._read_state(conn, recent, {i.external_id for i in items})
        cursor_out: dict[str, Any] = {
            "uidvalidity": uidvalidity,
            "last_uid": newest,
            "recent": recent,
        }
        if stuck:
            cursor_out["stuck"] = stuck
        # Incremental: only new mail is read, so this batch says nothing about deletions.
        return Batch(items=items, cursor=cursor_out, patches=patches)

    def _message(self, conn: imaplib.IMAP4, uidvalidity: str, meta: _Meta) -> ItemIn | None:
        if meta.size > MAX_MESSAGE_BYTES or meta.size < 0:
            parts = f"(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{PARTIAL_TEXT_BYTES}>)"
            status, data = conn.uid("FETCH", str(meta.uid), parts)
            if status != "OK":
                return None
            raw = b"".join(_literals(data))
            if not raw:
                return None
            if meta.size < 0:
                note = "服务器没有给出邮件大小，只读了开头，附件没有读取。"
            else:
                size_mb = meta.size // (1024 * 1024)
                note = f"邮件太大（{size_mb} MB），只读了开头，附件没有读取。"
        else:
            status, data = conn.uid("FETCH", str(meta.uid), "(BODY.PEEK[])")
            literals = _literals(data) if status == "OK" else []
            if not literals:
                return None
            raw, note = literals[0], ""
        try:
            return _item(uidvalidity, meta, raw, note)
        except Exception as exc:  # one odd message must never stop the mailbox
            return _unreadable(uidvalidity, meta, type(exc).__name__)

    def _read_state(
        self, conn: imaplib.IMAP4, recent: list[list[Any]], fresh: set[str]
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], list[list[Any]]]:
        """Read state of recent mail, which the user may have read on the phone since.
        Also returns `recent` without the messages the server no longer has."""
        older = [(int(e[0]), str(e[1])) for e in recent if e[1] not in fresh]
        if not older:
            return [], recent
        try:
            status, data = conn.uid("FETCH", ",".join(str(u) for u, _ in older), "(FLAGS)")
        except (OSError, imaplib.IMAP4.error):
            return [], recent
        if status != "OK":
            return [], recent
        metas = _metas(data)
        patches: list[tuple[str, str, dict[str, Any]]] = [
            ("email_message", ext, {"seen": metas[uid].seen}) for uid, ext in older if uid in metas
        ]
        kept = [e for e in recent if e[1] in fresh or int(e[0]) in metas]
        return patches, kept

    @staticmethod
    def _uidvalidity(conn: imaplib.IMAP4) -> str:
        _typ, data = conn.response("UIDVALIDITY")
        value = data[0] if data and data[0] else b""
        return value.decode() if isinstance(value, bytes) else str(value)
