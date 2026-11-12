# ruff: noqa: RUF001  (Chinese test subjects use full-width punctuation on purpose)
"""The IMAP email connector against a local fake IMAP server (ADR 0022)."""

import base64
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.db import DB_FILENAME
from apps.hub.core.domain import Actor
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.integrations import imap as imap_module
from apps.hub.integrations import service
from apps.hub.integrations.connectors import Batch, SyncError
from apps.hub.integrations.imap import ImapConnector, check_imap_config
from tests.hub.fake_imap import FakeImapServer, Mailbox
from tests.hub.support import hub_client

AUTH_CODE = "AUTHCODE-7Hq2Lr9W"  # a 163 client authorisation code
ADDRESS = "student@example.com"
OWNER = Actor(owner_id="local", source="test")


def internaldate(hours_ago: float = 1) -> str:
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    return when.strftime("%d-%b-%Y %H:%M:%S +0000")


def mail(subject: str, body: str, *, html: bool = False, attach: bool = False, n: int = 0) -> bytes:
    m = EmailMessage()
    m["From"] = "Canvas 通知 <notifications@example.com>"
    m["To"] = ADDRESS
    m["Subject"] = subject
    m["Date"] = "Tue, 10 Nov 2026 09:30:00 -0800"
    m["Message-ID"] = f"<{abs(hash(subject))}.{n}@example.com>"
    if html:
        m.set_content("plain fallback")
        m.add_alternative(f"<style>p{{}}</style><p>{body} &amp; more</p>", subtype="html")
    else:
        m.set_content(body)
    if attach:
        m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="syllabus.pdf")
    return m.as_bytes()


@pytest.fixture
def box() -> Mailbox:
    mailbox = Mailbox(username=ADDRESS, password=AUTH_CODE)
    mailbox.add(
        mail("作业提醒：Lab 3 明天截止", "请在明天之前提交。", attach=True),
        received=internaldate(2),
    )
    mailbox.add(
        mail("Midterm moved", "Now on Friday", html=True), seen=True, received=internaldate(1)
    )
    return mailbox


@pytest.fixture
def imap(box: Mailbox) -> Iterator[FakeImapServer]:
    server = FakeImapServer(box)
    yield server
    server.close()


def config(imap: FakeImapServer) -> dict[str, str]:
    return {"host": "127.0.0.1", "port": str(imap.port), "username": ADDRESS, "tls": "off"}


def fetch(
    imap: FakeImapServer, cursor: dict[str, Any] | None = None, code: str = AUTH_CODE
) -> Batch:
    return ImapConnector().fetch(code, cursor or {}, config(imap))


def test_messages_are_read_with_sender_subject_time_and_text(imap: FakeImapServer) -> None:
    batch = fetch(imap)
    assert batch.items is not None
    first, second = batch.items
    assert first.item_type == "email_message" and first.external_id.startswith("mid:<")
    assert first.title == "作业提醒：Lab 3 明天截止"
    assert first.body == "请在明天之前提交。"
    assert first.starts_at is not None  # the server's receive time
    assert abs(first.starts_at - (datetime.now(UTC) - timedelta(hours=2))) < timedelta(minutes=2)
    assert first.data["from_name"] == "Canvas 通知"
    assert first.data["from_address"] == "notifications@example.com"
    assert first.data["attachments"] == ["syllabus.pdf"] and first.data["seen"] is False
    assert second.body == "plain fallback" and second.data["seen"] is True
    assert batch.cursor["last_uid"] == 102 and batch.cursor["uidvalidity"] == "7"
    assert batch.complete is False  # incremental: never prunes


def test_html_only_mail_becomes_readable_text(imap: FakeImapServer, box: Mailbox) -> None:
    m = EmailMessage()
    m["Subject"] = "HTML only"
    m.set_content("<style>.x{}</style><p>Hello &amp; welcome</p>", subtype="html")
    box.add(m.as_bytes(), received=internaldate())
    (_, _, html_only) = fetch(imap).items or []
    assert html_only.body == "Hello & welcome"


def test_nothing_is_ever_changed_on_the_server(imap: FakeImapServer, box: Mailbox) -> None:
    fetch(imap)
    verbs = [c.split(" ", 1)[0] for c in box.commands]
    assert "EXAMINE" in verbs and "SELECT" not in verbs  # opened read-only
    assert not {"STORE", "EXPUNGE", "COPY", "MOVE", "APPEND", "DELETE", "CLOSE"} & set(verbs)
    bodies = [c for c in box.commands if c.startswith("UID FETCH") and "BODY" in c]
    assert bodies and all("BODY.PEEK" in c for c in bodies)  # never marks as read


def test_163s_id_requirement_is_met_before_opening_the_mailbox(
    imap: FakeImapServer, box: Mailbox
) -> None:
    fetch(imap)
    order = [c.split(" ", 1)[0] for c in box.commands]
    assert order.index("ID") < order.index("EXAMINE")


def test_the_next_sync_reads_only_new_mail(imap: FakeImapServer, box: Mailbox) -> None:
    first = fetch(imap)
    box.add(mail("New one", "hello"), received=internaldate(0.1))
    again = fetch(imap, first.cursor)
    assert [i.title for i in again.items or []] == ["New one"]
    assert again.cursor["last_uid"] == 103
    quiet = fetch(imap, again.cursor)  # "n:*" returns the last uid even with nothing new
    assert quiet.items == []


def test_a_backlog_is_read_oldest_first_over_several_syncs(
    imap: FakeImapServer, box: Mailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    for n in range(3):
        box.add(mail(f"Backlog {n}", "x", n=n), received=internaldate(0.5))
    monkeypatch.setattr(imap_module, "MAX_PER_SYNC", 2)
    seen: list[str] = []
    cursor: dict[str, Any] = {}
    for _ in range(4):
        batch = fetch(imap, cursor)
        seen += [i.title for i in batch.items or []]
        cursor = batch.cursor
    assert seen == [
        "作业提醒：Lab 3 明天截止",
        "Midterm moved",
        "Backlog 0",
        "Backlog 1",
        "Backlog 2",
    ]


def test_a_huge_message_is_kept_as_its_beginning(
    imap: FakeImapServer, box: Mailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    box.add(mail("Huge", "start of the text " * 50, attach=True), received=internaldate())
    monkeypatch.setattr(imap_module, "MAX_MESSAGE_BYTES", 400)
    items = fetch(imap).items or []
    huge = next(i for i in items if i.title == "Huge")
    assert "太大" in huge.body and "start of the text" in huge.body
    assert "BODY.PEEK[HEADER]" in " ".join(box.commands)


def test_mislabelled_and_unknown_charsets_do_not_stop_the_mailbox(
    imap: FakeImapServer, box: Mailbox
) -> None:
    gbk_only = "喆镕"  # in GBK, not in GB2312: Chinese mail often labels it gb2312 anyway
    encoded = base64.b64encode(gbk_only.encode("gbk")).decode()
    for subject in (f"=?gb2312?B?{encoded}?=", "=?x-unknown?Q?abc?="):
        raw = f"Subject: {subject}\r\nFrom: a@example.com\r\n\r\nbody\r\n".encode()
        box.add(raw, received=internaldate())
    items = fetch(imap).items or []
    titles = [i.title for i in items[2:]]
    assert titles[0] == gbk_only
    assert len(titles) == 2 and all(t.isprintable() for t in titles)


def test_a_message_that_cannot_be_read_becomes_a_note(
    imap: FakeImapServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("odd structure")

    monkeypatch.setattr(imap_module, "_item", broken)
    batch = fetch(imap)
    assert [i.title for i in batch.items or []] == ["（无法解析的邮件）"] * 2
    assert batch.cursor["last_uid"] == 102  # it moved on instead of failing forever


def test_a_refused_message_is_retried_not_skipped(imap: FakeImapServer, box: Mailbox) -> None:
    box.refuse_uid = 102
    first = fetch(imap)
    assert [i.title for i in first.items or []] == ["作业提醒：Lab 3 明天截止"]
    assert first.cursor["last_uid"] == 101
    box.refuse_uid = None
    again = fetch(imap, first.cursor)
    assert [i.title for i in again.items or []] == ["Midterm moved"]


def test_a_dropped_connection_keeps_what_was_read(imap: FakeImapServer, box: Mailbox) -> None:
    box.drop_at_uid = 102
    first = fetch(imap)
    assert [i.title for i in first.items or []] == ["作业提醒：Lab 3 明天截止"]
    assert first.cursor["last_uid"] == 101


def test_a_message_refused_for_good_does_not_block_later_mail(
    imap: FakeImapServer, box: Mailbox
) -> None:
    box.refuse_uid = 102
    box.add(mail("After it", "x"), received=internaldate(0.5))
    cursor: dict[str, Any] = {}
    titles: list[str] = []
    for _ in range(imap_module.MAX_TRIES):
        batch = fetch(imap, cursor)
        titles += [i.title for i in batch.items or []]
        cursor = batch.cursor
    assert titles == ["作业提醒：Lab 3 明天截止", "（无法解析的邮件）", "After it"]
    assert cursor["last_uid"] == 103 and "stuck" not in cursor


def test_two_mails_sharing_a_message_id_are_both_kept(imap: FakeImapServer, box: Mailbox) -> None:
    original = mail("Real notice", "real", n=5)
    box.add(original, received=internaldate(0.5))
    box.add(original.replace(b"Real notice", b"Spoofed copy"), received=internaldate(0.2))
    items = (fetch(imap).items or [])[2:]
    assert [i.title for i in items] == ["Real notice", "Spoofed copy"]
    assert items[0].external_id != items[1].external_id


def test_read_state_is_checked_only_for_mail_still_recent_and_present(
    imap: FakeImapServer, box: Mailbox
) -> None:
    first = fetch(imap)
    assert [e[0] for e in first.cursor["recent"]] == [101, 102]
    week_ago = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    aged = {**first.cursor, "recent": [[101, "mid:x", week_ago], first.cursor["recent"][1]]}
    box.messages.pop(1)  # 102 was deleted on the phone
    again = fetch(imap, aged)
    assert again.cursor["recent"] == [] and again.patches == []


def test_read_state_is_refreshed_for_recent_mail(imap: FakeImapServer, box: Mailbox) -> None:
    first = fetch(imap)
    box.messages[0].seen = True  # read on the phone
    again = fetch(imap, first.cursor)
    lab_id = (first.items or [])[0].external_id
    assert ("email_message", lab_id, {"seen": True}) in again.patches


def test_a_renumbered_folder_does_not_duplicate_mail(imap: FakeImapServer, box: Mailbox) -> None:
    first = fetch(imap)
    box.uidvalidity = 8
    again = fetch(imap, first.cursor)
    assert {i.external_id for i in again.items or []} == {i.external_id for i in first.items or []}
    assert again.cursor["uidvalidity"] == "8"


def test_a_wrong_code_says_what_to_use(imap: FakeImapServer) -> None:
    with pytest.raises(SyncError, match="授权码") as raised:
        fetch(imap, code="my-real-password")
    assert "my-real-password" not in str(raised.value)


def test_a_code_with_a_line_break_is_refused_before_sending(imap: FakeImapServer) -> None:
    with pytest.raises(SyncError, match="paste it again"):
        fetch(imap, code="AUTH\r\nCODE")


def test_an_unreachable_server_is_an_error() -> None:
    cfg = {"host": "127.0.0.1", "port": "9", "username": ADDRESS, "tls": "off"}
    with pytest.raises(SyncError, match="could not be reached"):
        ImapConnector().fetch(AUTH_CODE, {}, cfg)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            {"host": "IMAP.163.com", "username": ADDRESS},
            {
                "host": "imap.163.com",
                "port": "993",
                "username": ADDRESS,
                "folder": "INBOX",
                "tls": "on",
            },
        ),
        (
            {"host": "imap.gmail.com", "username": "me@example.com", "folder": "[Gmail]/All Mail"},
            {
                "host": "imap.gmail.com",
                "port": "993",
                "username": "me@example.com",
                "folder": "[Gmail]/All Mail",
                "tls": "on",
            },
        ),
    ],
)
def test_settings_are_normalised(given: dict[str, str], expected: dict[str, str]) -> None:
    assert check_imap_config(given) == expected


@pytest.mark.parametrize(
    "bad",
    [
        {"host": "imap.163.com"},  # no address
        {"host": "imap.163.com", "username": "not-an-address"},
        {"host": "imap.163.com", "username": 'a"b@example.com'},  # LOGIN takes it unquoted
        {"host": "imap.163.com", "username": ADDRESS, "tls": "off"},  # plain text off-PC
        {"host": "imap.163.com", "username": ADDRESS, "password": "x"},  # secrets are not config
        {"host": "imap 163", "username": ADDRESS},
        {"host": "imap.163.com", "username": ADDRESS, "folder": 'IN"BOX'},
        {"host": "imap.163.com", "username": ADDRESS, "folder": "已发送"},  # needs UTF-7
        {"host": "imap.163.com", "username": ADDRESS, "port": "99999"},
    ],
)
def test_bad_settings_are_refused(bad: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        check_imap_config(bad)


@pytest.fixture
def store() -> credentials.MemorySecretStore:
    return credentials.MemorySecretStore()


@pytest.fixture
def client(data_dir: Path, store: credentials.MemorySecretStore) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False), secret_store=store) as c:
        yield c


def connect(client: TestClient, imap: FakeImapServer, code: str = AUTH_CODE) -> dict[str, Any]:
    assert client.put("/credentials/mail.code", json={"secret": code}).status_code == 200
    body = {
        "kind": "email",
        "name": "163 邮箱",
        "credential_name": "mail.code",
        "config": config(imap),
    }
    created = client.post("/integrations", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def sync(client: TestClient, store: Any, integration: dict[str, Any]) -> dict[str, int]:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    return service.sync(engine, store, OWNER, integration["id"], datetime.now(UTC))


def test_through_the_hub_mail_is_stored_once_kept_and_its_read_state_follows(
    client: TestClient, imap: FakeImapServer, box: Mailbox, store: Any
) -> None:
    integration = connect(client, imap)
    assert sync(client, store, integration)["added"] == 2
    box.add(mail("New one", "hello"), received=internaldate(0.1))
    box.messages[0].seen = True
    counts = sync(client, store, integration)
    assert counts["added"] == 1 and counts["removed"] == 0  # older mail is not pruned
    assert counts["updated"] == 1  # the lab reminder is now read
    url = f"/integrations/{integration['id']}/items"
    newest = client.get(url, params={"order": "desc", "item_type": "email_message"}).json()
    assert [i["title"] for i in newest] == ["New one", "Midterm moved", "作业提醒：Lab 3 明天截止"]
    assert newest[2]["data"]["seen"] is True
    box.uidvalidity = 9  # the server renumbered the folder
    sync(client, store, integration)
    assert len(client.get(url).json()) == 3  # no duplicates


def test_the_code_leaves_no_trace(
    client: TestClient,
    imap: FakeImapServer,
    store: Any,
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    integration = connect(client, imap, code="WRONGCODE-abc123")
    with caplog.at_level(logging.DEBUG), pytest.raises(SyncError):
        sync(client, store, integration)
    after = client.get(f"/integrations/{integration['id']}").json()
    assert after["status"] == "error" and "授权码" in after["last_error"]
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        logged = json.dumps([e.model_dump(mode="json") for e in audit.list_events(s, "local")])
    stored = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    for where in (json.dumps(after), logged, caplog.text):
        assert "WRONGCODE-abc123" not in where
    assert b"WRONGCODE-abc123" not in stored


# --- History backfill (T-0027, ADR 0031) -----------------------------------------------


def _history_box(old: int, new: int = 2) -> Mailbox:
    mailbox = Mailbox(username=ADDRESS, password=AUTH_CODE)
    for n in range(old):  # added first, so they get the lower UIDs, like real history
        mailbox.add(mail(f"Old {n}", "history", n=n), received=internaldate(24 * (60 + n)))
    for n in range(new):
        mailbox.add(mail(f"New {n}", "recent", n=100 + n), received=internaldate(1 + n))
    return mailbox


def _titles(batch: Batch) -> list[str]:
    return [i.title for i in batch.items or []]


def test_history_is_read_after_new_mail_newest_first_until_done() -> None:
    mailbox = _history_box(old=3)
    server = FakeImapServer(mailbox)
    try:
        first = fetch(server)
        # New mail first (oldest first), then history from the newest old mail down.
        assert _titles(first) == ["New 0", "New 1", "Old 2", "Old 1", "Old 0"]
        assert first.cursor["backfill_done"] is True
        again = fetch(server, dict(first.cursor))
        assert _titles(again) == []  # nothing new, history complete
    finally:
        server.close()


def test_long_history_is_read_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap_module, "MAX_BACKFILL_PER_SYNC", 2)
    mailbox = _history_box(old=5, new=1)
    server = FakeImapServer(mailbox)
    try:
        seen: list[str] = []
        cursor: dict[str, Any] = {}
        for _ in range(4):
            batch = fetch(server, cursor)
            seen += _titles(batch)
            cursor = dict(batch.cursor)
        assert seen == ["New 0", "Old 4", "Old 3", "Old 2", "Old 1", "Old 0"]
        assert cursor["backfill_done"] is True
    finally:
        server.close()


def test_a_cursor_from_before_backfill_starts_history_below_what_it_read() -> None:
    mailbox = _history_box(old=2, new=2)
    server = FakeImapServer(mailbox)
    try:
        newest_uid = max(m.uid for m in mailbox.messages)
        old_cursor = {"uidvalidity": "7", "last_uid": newest_uid, "recent": []}
        batch = fetch(server, old_cursor)
        # Everything below last_uid is read again; stored mail is recognised by its id.
        assert _titles(batch) == ["New 1", "New 0", "Old 1", "Old 0"]
        assert batch.cursor["backfill_done"] is True
    finally:
        server.close()


def test_a_refused_history_message_is_retried_then_noted_and_never_blocks() -> None:
    mailbox = _history_box(old=3)
    mailbox.refuse_uid = mailbox.messages[1].uid  # "Old 1"
    server = FakeImapServer(mailbox)
    try:
        cursor: dict[str, Any] = {}
        titles: list[str] = []
        for _ in range(3):  # MAX_TRIES syncs, then it becomes a note
            batch = fetch(server, cursor)
            titles += _titles(batch)
            cursor = dict(batch.cursor)
        assert titles[:3] == ["New 0", "New 1", "Old 2"]
        assert titles[3:] == ["（无法解析的邮件）", "Old 0"]
        assert cursor["backfill_done"] is True and "backfill_stuck" not in cursor
    finally:
        server.close()


def test_a_quiet_mailbox_still_reads_its_history() -> None:
    mailbox = _history_box(old=3, new=0)  # nothing in the first-sync window
    server = FakeImapServer(mailbox)
    try:
        batch = fetch(server)
        assert _titles(batch) == ["Old 2", "Old 1", "Old 0"]
        assert batch.cursor["backfill_done"] is True
        mailbox.uidvalidity = 8  # renumbered and still quiet: history again
        again = fetch(server, dict(batch.cursor))
        assert _titles(again) == ["Old 2", "Old 1", "Old 0"]
    finally:
        server.close()


def test_a_deadline_mid_history_keeps_the_bound_at_the_last_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = _history_box(old=4, new=0)
    server = FakeImapServer(mailbox)
    real_message = ImapConnector._message
    real_monotonic = imap_module.time.monotonic
    state = {"reads": 0, "late": False}

    def message(self: ImapConnector, *args: Any) -> Any:
        state["reads"] += 1
        if state["reads"] == 2:  # after "Old 3" and "Old 2", the sync's time is up
            state["late"] = True
        return real_message(self, *args)

    import time as real_time
    import types

    clock = types.SimpleNamespace(
        **{k: getattr(real_time, k) for k in dir(real_time) if not k.startswith("_")}
    )
    clock.monotonic = lambda: real_monotonic() + (10_000 if state["late"] else 0)
    monkeypatch.setattr(ImapConnector, "_message", message)
    monkeypatch.setattr(imap_module, "time", clock)
    try:
        batch = fetch(server)
        assert _titles(batch) == ["Old 3", "Old 2"]
        assert batch.cursor["backfill_done"] is False
        assert batch.cursor["backfill_below"] == mailbox.messages[2].uid  # "Old 2"
        state["late"] = False
        rest = fetch(server, dict(batch.cursor))
        assert _titles(rest) == ["Old 1", "Old 0"] and rest.cursor["backfill_done"] is True
    finally:
        server.close()


def test_a_message_listed_but_gone_is_skipped() -> None:
    mailbox = _history_box(old=3, new=0)
    mailbox.vanish_uid = mailbox.messages[1].uid  # "Old 1" was expunged meanwhile
    server = FakeImapServer(mailbox)
    try:
        batch = fetch(server)
        assert _titles(batch) == ["Old 2", "Old 0"] and batch.cursor["backfill_done"] is True
    finally:
        server.close()


def test_exactly_one_batch_of_history_is_done_in_one_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap_module, "MAX_BACKFILL_PER_SYNC", 3)
    mailbox = _history_box(old=3, new=0)
    server = FakeImapServer(mailbox)
    try:
        batch = fetch(server)
        assert len(_titles(batch)) == 3 and batch.cursor["backfill_done"] is True
    finally:
        server.close()


def test_an_old_cursor_rereads_stored_mail_without_adding_it_again(
    client: TestClient, store: Any
) -> None:
    box = _history_box(old=2, new=2)  # history first: older mail has the lower UIDs
    server = FakeImapServer(box)
    try:
        integration = connect(client, server)
        first = sync(client, store, integration)
        assert first["added"] == 4  # two recent + two from history
        with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
            from apps.hub.integrations.models import IntegrationRow

            row = s.get(IntegrationRow, integration["id"])
            assert row is not None
            row.cursor = {k: v for k, v in row.cursor.items() if not k.startswith("backfill")}
            s.commit()  # what a cursor from before T-0027 looks like
        again = sync(client, store, integration)
        assert again["added"] == 0  # everything re-read is recognised
        assert len(client.get(f"/integrations/{integration['id']}/items").json()) == 4
    finally:
        server.close()


def test_a_renumbered_mailbox_restarts_history() -> None:
    mailbox = _history_box(old=2)
    server = FakeImapServer(mailbox)
    try:
        done = fetch(server)
        mailbox.uidvalidity = 8  # the server renumbered every message
        again = fetch(server, dict(done.cursor))
        assert set(_titles(again)) == {"New 0", "New 1", "Old 1", "Old 0"}
    finally:
        server.close()


def test_a_refused_search_all_leaves_history_for_the_next_sync() -> None:
    mailbox = _history_box(old=2, new=0)
    mailbox.refuse_search_all = True
    server = FakeImapServer(mailbox)
    try:
        batch = fetch(server)
        assert _titles(batch) == [] and batch.cursor["backfill_done"] is False
        mailbox.refuse_search_all = False
        again = fetch(server, dict(batch.cursor))
        assert _titles(again) == ["Old 1", "Old 0"] and again.cursor["backfill_done"] is True
    finally:
        server.close()


def test_a_long_reread_never_adds_a_duplicate_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap_module, "MAX_BACKFILL_PER_SYNC", 1)
    mailbox = _history_box(old=0, new=3)  # all three were stored by the old connector
    refused = mailbox.messages[0]
    mailbox.refuse_uid = refused.uid
    server = FakeImapServer(mailbox)
    try:
        cursor: dict[str, Any] = {
            "uidvalidity": "7",
            "last_uid": max(m.uid for m in mailbox.messages),
            "recent": [],
        }
        titles: list[str] = []
        for _ in range(8):  # one UID per sync; the refused one is retried MAX_TRIES times
            batch = fetch(server, cursor)
            titles += _titles(batch)
            cursor = dict(batch.cursor)
        assert "（无法解析的邮件）" not in titles  # stored already: skipped, never noted
        assert cursor["backfill_done"] is True and "reread_upto" not in cursor
    finally:
        server.close()


def test_mail_text_keeps_its_paragraphs() -> None:
    plain = EmailMessage()
    plain["Subject"] = "p"
    plain.set_content("第一段  第一行\n第一段 第二行\n\n\n\n第二段")
    assert imap_module._text_of(plain) == "第一段 第一行\n第一段 第二行\n\n第二段"
    rich = EmailMessage()
    rich["Subject"] = "h"
    rich.set_content(
        "<div>Hello<br>world</div><p>Second&nbsp;para</p><script>x()</script>", subtype="html"
    )
    text = imap_module._text_of(rich)
    assert text.splitlines()[:2] == ["Hello", "world"] and "Second para" in text
    assert "x()" not in text
