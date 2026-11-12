from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from apps.hub.audit.models import AuditEventRow
from apps.hub.core.settings import Settings
from apps.hub.credentials import service as credentials
from apps.hub.models import service as models
from apps.hub.models.fake import FakeProvider
from apps.hub.summaries import service as summaries
from apps.hub.triage.groups import course_keys
from apps.hub.triage.rules import MailFacts, matches
from packages.contracts.triage import Selector
from tests.hub.support import hub_client
from tests.hub.test_summaries import KEY, OWNER, mail, mailbox

BIG = 10_000_000


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[tuple[TestClient, Engine, Any]]:
    store = credentials.MemorySecretStore()
    with hub_client(Settings(data_dir=tmp_path / "data"), secret_store=store) as client:
        engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
        with Session(engine) as session:
            credentials.put(session, OWNER, store, models.CREDENTIAL, KEY, "")
        yield client, engine, store


def summarise(engine: Engine, store: Any) -> None:
    fake = FakeProvider()
    while summaries.run(engine, store, OWNER, fake, "fake", BIG, datetime.now(UTC)):
        pass


def seed(engine: Engine, store: Any) -> dict[str, str]:
    """Twelve unread mails: 6 Handshake digests, 2 grade notices, 2 to act on, 2 others."""
    box = mailbox(engine)
    now = datetime.now(UTC)
    ids: dict[str, str] = {}
    for i in range(6):
        ids[f"hs{i}"] = mail(
            engine,
            box,
            f"Weekly digest {i}",
            at=now - timedelta(hours=i + 1),
            from_name="Handshake",
            from_address="jobs@g.joinhandshake.com",
        )
    for i in range(2):
        ids[f"grade{i}"] = mail(
            engine, box, f"成绩已发布 Quiz {i}", at=now - timedelta(hours=10 + i)
        )
    for i in range(2):
        ids[f"act{i}"] = mail(engine, box, f"Lab {i} 截止", at=now - timedelta(hours=20 + i))
    ids["old"] = mail(engine, box, "Club news", at=now - timedelta(days=3))
    ids["read"] = mail(engine, box, "Already read", at=now - timedelta(days=4), seen=True)
    summarise(engine, store)
    return ids


def view(client: TestClient) -> dict[str, Any]:
    r = client.get("/triage")
    assert r.status_code == 200, r.text
    return r.json()


def group(v: dict[str, Any], key: str) -> dict[str, Any]:
    return next(g for g in v["groups"] if g["key"] == key)


def test_every_open_mail_is_in_exactly_one_group(hub) -> None:
    client, engine, store = hub
    ids = seed(engine, store)
    v = view(client)
    assert v["unread_count"] == 11 and v["open_count"] == 11
    grouped = [i for g in v["groups"] for i in g["item_ids"]]
    assert sorted(grouped) == sorted(set(grouped)) and len(grouped) == 11
    assert ids["read"] not in grouped
    assert sum(g["count"] for g in v["groups"]) == v["open_count"]
    hs = group(v, "sender:joinhandshake.com")  # subdomains share one group
    assert hs["count"] == 6 and hs["rule"] is not None
    assert "joinhandshake.com" in hs["rule_description"]
    assert group(v, "grades")["count"] == 2 and group(v, "grades")["rule"] is None


def test_a_group_batch_drops_open_and_undo_restores_it(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    hs = group(view(client), "sender:joinhandshake.com")
    r = client.post("/triage/handle", json={"item_ids": hs["item_ids"], "group_key": hs["key"]})
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["count"] == 6 and batch["status"] == "applied"
    v = view(client)
    assert v["open_count"] == 5 and v["recent"][0]["id"] == batch["id"]
    assert all(g["key"] != hs["key"] for g in v["groups"])
    again = client.post("/triage/handle", json={"item_ids": hs["item_ids"]})
    assert again.status_code == 409  # nothing left to handle
    undone = client.post(f"/triage/batches/{batch['id']}/undo")
    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert view(client)["open_count"] == 11
    assert client.post(f"/triage/batches/{batch['id']}/undo").status_code == 409


def test_a_saved_rule_covers_new_mail_and_undo_switches_it_off(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    hs = group(view(client), "sender:joinhandshake.com")
    batch = client.post(
        "/triage/handle",
        json={"item_ids": hs["item_ids"], "group_key": hs["key"], "save_rule": True},
    ).json()
    assert batch["rule_id"]
    box = mailbox(engine)
    new = mail(
        engine,
        box,
        "Weekly digest new",
        from_name="Handshake",
        from_address="digest@joinhandshake.com",
        at=datetime.now(UTC),
    )
    summarise(engine, store)
    v = view(client)
    marks = {m["item_id"]: m for m in v["handled"]}
    assert marks[new]["by"] == "rule" and marks[new]["rule_id"] == batch["rule_id"]
    assert v["rules"][0]["enabled"] and v["rules"][0]["matched"] >= 1
    client.post(f"/triage/batches/{batch['id']}/undo")
    v = view(client)
    assert not v["rules"][0]["enabled"] and new not in {m["item_id"] for m in v["handled"]}


def test_marking_one_mail_unhandled_beats_a_rule(hub) -> None:
    client, engine, store = hub
    ids = seed(engine, store)
    hs = group(view(client), "sender:joinhandshake.com")
    client.post(
        "/triage/handle",
        json={"item_ids": hs["item_ids"], "group_key": hs["key"], "save_rule": True},
    )
    r = client.put(f"/triage/items/{ids['hs0']}", json={"handled": False})
    assert r.status_code == 200
    assert ids["hs0"] not in {m["item_id"] for m in view(client)["handled"]}
    rule_id = view(client)["rules"][0]["id"]
    assert (
        client.patch(f"/triage/rules/{rule_id}", json={"enabled": False}).json()["enabled"] is False
    )


def test_another_owners_or_unknown_ids_are_ignored(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    other_box = mailbox(engine, owner="other")
    theirs = mail(engine, other_box, "Not yours", owner="other")
    r = client.post("/triage/handle", json={"item_ids": [theirs, "01JZZZZZZZZZZZZZZZZZZZZZZZ"]})
    assert r.status_code == 409
    assert client.put(f"/triage/items/{theirs}", json={"handled": True}).status_code == 404
    assert client.post("/triage/batches/01JZZZZZZZZZZZZZZZZZZZZZZZ/undo").status_code == 404


def test_a_rule_can_only_be_saved_for_a_group_that_offers_one(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    grades = group(view(client), "grades")
    r = client.post(
        "/triage/handle",
        json={"item_ids": grades["item_ids"], "group_key": "grades", "save_rule": True},
    )
    assert r.status_code == 422
    r = client.post("/triage/handle", json={"item_ids": grades["item_ids"], "group_key": "nope"})
    assert r.status_code == 409


def test_the_audit_log_holds_counts_not_mail_text(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    hs = group(view(client), "sender:joinhandshake.com")
    client.post("/triage/handle", json={"item_ids": hs["item_ids"], "group_key": hs["key"]})
    with Session(engine) as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.entity_type == "triage_batch")
        ).all()
    assert len(events) == 1 and events[0].detail["count"] == 6
    assert "Weekly digest" not in repr(events[0].detail)


def facts(sender: str = "a@b.com", subject: str = "hello") -> MailFacts:
    return MailFacts("i", None, "Name", sender, subject, False, None)


def test_rule_text_is_literal_and_small() -> None:
    sel = Selector.model_validate(
        {"all_of": [{"kind": "text", "field": "subject", "value": ".*x"}]}
    )
    assert not matches(sel, facts(subject="anything x"), date(2026, 11, 11))
    assert matches(sel, facts(subject="has .*x in it"), date(2026, 11, 11))
    for bad in (
        {"all_of": [{"kind": "text", "field": "subject", "value": "ab"}]},  # ASCII under 3
        {"all_of": [{"kind": "text", "field": "body", "value": "abc"}]},  # unknown field
        {"all_of": [{"kind": "text", "field": "subject", "value": "a\x07bc"}]},  # control char
        {"all_of": [{"kind": "flag", "flag": "low_value"}] * 5},  # more than 4
        {"all_of": []},
        {"any_of": [{"kind": "flag", "flag": "low_value"}]},
    ):
        with pytest.raises(ValidationError):
            Selector.model_validate(bad)


def test_domain_equals_covers_subdomains_only() -> None:
    sel = Selector.model_validate(
        {
            "all_of": [
                {
                    "kind": "text",
                    "field": "sender_domain",
                    "op": "equals",
                    "value": "joinhandshake.com",
                }
            ]
        }
    )
    today = date(2026, 11, 11)
    assert matches(sel, facts("x@g.joinhandshake.com"), today)
    assert matches(sel, facts("x@joinhandshake.com"), today)
    assert not matches(sel, facts("x@notjoinhandshake.com"), today)


def test_course_keys_match_what_mail_senders_carry() -> None:
    codes = [
        "F26 CIS D022A 54Y Beg Prog Method C++",
        "F26 MATH D001A 49 Calculus I",
        "DA ISP New Student",
    ]
    assert course_keys(codes) == ["CIS D022A", "MATH D001A"]


def test_undo_after_later_changes_keeps_the_later_ones(hub) -> None:
    client, engine, store = hub
    ids = seed(engine, store)
    x, y = ids["old"], ids["act0"]
    a = client.post("/triage/handle", json={"item_ids": [x, y]}).json()
    client.put(f"/triage/items/{x}", json={"handled": False})  # by hand, after batch A
    b = client.post("/triage/handle", json={"item_ids": [x]}).json()
    client.put(f"/triage/items/{y}", json={"handled": True})  # by hand: y leaves batch A
    client.post(f"/triage/batches/{a['id']}/undo")
    handled = {m["item_id"] for m in view(client)["handled"]}
    assert x in handled and y in handled  # undo A touched neither: both changed later
    client.post(f"/triage/batches/{b['id']}/undo")
    handled = {m["item_id"] for m in view(client)["handled"]}
    assert x not in handled and y in handled  # undo B restores x's manual 未处理


def test_sender_rules_stay_narrow_and_never_cover_important_senders(hub) -> None:
    client, engine, store = hub
    seed(engine, store)
    box = mailbox(engine)
    now = datetime.now(UTC)
    for i in range(5):  # a sender that also sends grades gets no rule
        mail(
            engine,
            box,
            f"Weekly digest canvas {i}",
            at=now - timedelta(minutes=i + 1),
            from_name="Canvas",
            from_address="notify@instructure.com",
        )
    mail(
        engine,
        box,
        "成绩已发布 Exam",
        at=now - timedelta(minutes=30),
        from_name="Canvas",
        from_address="notify@instructure.com",
    )
    summarise(engine, store)
    v = view(client)
    canvas = group(v, "sender:instructure.com")
    assert canvas["count"] == 5 and canvas["rule"] is None
    hs = group(v, "sender:joinhandshake.com")
    flags = {(c.get("flag"), c.get("value")) for c in hs["rule"]["all_of"] if c["kind"] == "flag"}
    assert flags == {("low_value", True), ("action_needed", False), ("deadline_past", False)}
    assert all(g["rule"] is None for g in v["groups"] if g["kind"] == "low_value")
    first = client.post(
        "/triage/handle",
        json={"item_ids": hs["item_ids"], "group_key": hs["key"], "save_rule": True},
    ).json()
    assert first["rule_id"]
    for one in hs["item_ids"][:5]:  # five back by hand: a sender group again
        client.put(f"/triage/items/{one}", json={"handled": False})
    again = group(view(client), hs["key"])
    second = client.post(
        "/triage/handle",
        json={"item_ids": again["item_ids"], "group_key": hs["key"], "save_rule": True},
    ).json()
    assert second["rule_id"] is None  # the same rule exists and is on: no duplicate
    assert len(view(client)["rules"]) == 1


def test_grade_words_are_whole_words() -> None:
    from apps.hub.triage.groups import _is_grade

    assert _is_grade(facts(subject="Your grade is posted"))
    assert _is_grade(facts(subject="成绩已发布"))
    assert not _is_grade(facts(subject="Upgrade your plan"))
    assert not _is_grade(facts(subject="use an underscore"))


def test_country_domains_keep_their_owner_and_bare_suffixes_are_refused() -> None:
    assert facts("a@x.example.com.cn").domain == "example.com.cn"
    assert facts("a@g.joinhandshake.com").domain == "joinhandshake.com"
    for value in ("com.cn", "edu.cn", "com"):
        with pytest.raises(ValidationError):
            Selector.model_validate(
                {
                    "all_of": [
                        {"kind": "text", "field": "sender_domain", "op": "equals", "value": value}
                    ]
                }
            )
