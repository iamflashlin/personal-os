"""Mail triage: an in-app 已处理 state, groups, batches with undo, rules (ADR 0034).

Handled is decided at read time:
1. an explicit mark on the mail (handled / unhandled) wins;
2. otherwise the mail is handled when an enabled rule matches it.
So a rule covers new mail as soon as it is synced and summarised. The mailbox itself is
never changed (ADR 0022), and every change here comes from a person's click.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.integrations import service as integrations
from apps.hub.summaries import service as summaries
from apps.hub.triage.groups import group
from apps.hub.triage.models import MailTriageStateRow, TriageBatchRow, TriageRuleRow
from apps.hub.triage.rules import MailFacts, describe, matches
from packages.contracts.triage import (
    BatchStatus,
    HandledBy,
    HandledMark,
    HandleRequest,
    Selector,
    TriageBatch,
    TriageRule,
    TriageView,
)

EMAIL = "email_message"
RECENT = 10
HANDLED, UNHANDLED, NONE = "handled", "unhandled", "none"


def _facts(session: Session, actor: Actor) -> list[MailFacts]:
    """Every mail of this owner, with its summary only when it is fresh and `ok`."""
    fresh = {s.item_id: s for s in summaries.ok_summaries(session, actor)}
    out: list[MailFacts] = []
    for h in integrations.item_heads(session, actor, EMAIL):
        s = fresh.get(h.id)
        if s is not None and h.changed > s.updated_at:
            s = None  # changed after its summary: not trusted until summarised again
        out.append(MailFacts(h.id, h.received, h.from_name, h.from_address, h.subject, h.seen, s))
    return out


def _marks(session: Session, actor: Actor) -> dict[str, MailTriageStateRow]:
    rows = session.scalars(
        select(MailTriageStateRow).where(MailTriageStateRow.owner_id == actor.owner_id)
    )
    return {r.item_id: r for r in rows}


def _rules(session: Session, actor: Actor) -> list[TriageRuleRow]:
    return list(
        session.scalars(
            select(TriageRuleRow)
            .where(TriageRuleRow.owner_id == actor.owner_id)
            .order_by(TriageRuleRow.created_at)
        )
    )


def _handled(
    facts: list[MailFacts],
    marks: dict[str, MailTriageStateRow],
    rules: list[TriageRuleRow],
    today: date,
) -> dict[str, HandledMark]:
    enabled = [(r, Selector.model_validate(r.selector)) for r in rules if r.enabled]
    out: dict[str, HandledMark] = {}
    for f in facts:
        mark = marks.get(f.item_id)
        if mark is not None and mark.state == HANDLED:
            by = HandledBy.batch if mark.batch_id else HandledBy.manual
            out[f.item_id] = HandledMark(
                item_id=f.item_id, by=by, batch_id=mark.batch_id, rule_id=None
            )
            continue
        if mark is not None and mark.state == UNHANDLED:
            continue
        rule = next((r for r, sel in enabled if matches(sel, f, today)), None)
        if rule is not None:
            out[f.item_id] = HandledMark(
                item_id=f.item_id, by=HandledBy.rule, batch_id=None, rule_id=rule.id
            )
    return out


def _batch(row: TriageBatchRow) -> TriageBatch:
    return TriageBatch(
        id=row.id,
        kind=row.kind,
        status=BatchStatus(row.status),
        label=row.label,
        description=f"标记 {len(row.applied_ids)} 封为已处理",
        count=len(row.applied_ids),
        item_ids=list(row.applied_ids),
        rule_id=row.rule_id,
        applied_at=row.applied_at,
        undone_at=row.undone_at,
        version=row.version,
    )


def _rule(row: TriageRuleRow, matched: int) -> TriageRule:
    selector = Selector.model_validate(row.selector)
    return TriageRule(
        id=row.id,
        name=row.name,
        selector=selector,
        description=describe(selector),
        enabled=row.enabled,
        matched=matched,
        created_at=row.created_at,
        version=row.version,
    )


def view(session: Session, actor: Actor, today: date) -> TriageView:
    facts = _facts(session, actor)
    rules = _rules(session, actor)
    handled = _handled(facts, _marks(session, actor), rules, today)
    unread = [f for f in facts if not f.seen]
    open_ = [f for f in unread if f.item_id not in handled]
    by_rule = [m.rule_id for m in handled.values() if m.rule_id]
    batches = session.scalars(
        select(TriageBatchRow)
        .where(TriageBatchRow.owner_id == actor.owner_id)
        .order_by(TriageBatchRow.created_at.desc(), TriageBatchRow.id.desc())
        .limit(RECENT)
    )
    return TriageView(
        open_count=len(open_),
        unread_count=len(unread),
        unsummarised=sum(1 for f in open_ if f.summary is None),
        groups=group(open_, today, integrations.course_codes(session, actor), facts),
        handled=list(handled.values()),
        recent=[_batch(b) for b in batches],
        rules=[_rule(r, by_rule.count(r.id)) for r in rules],
    )


def _set(
    session: Session, actor: Actor, item_id: str, state: str, batch_id: str | None
) -> MailTriageStateRow:
    row = session.scalar(
        select(MailTriageStateRow).where(
            MailTriageStateRow.owner_id == actor.owner_id, MailTriageStateRow.item_id == item_id
        )
    )
    if row is None:
        row = MailTriageStateRow(
            owner_id=actor.owner_id,
            source=actor.source,
            version=1,
            item_id=item_id,
            state=NONE,
            prev_state=NONE,
        )
        session.add(row)
    row.prev_state, row.state, row.batch_id = row.state, state, batch_id
    return row


def handle(
    session: Session, actor: Actor, req: HandleRequest, today: date, now: datetime
) -> TriageBatch:
    """Mark mails 已处理 in one batch. With a group key, only that group's current mails
    are touched, and `save_rule` saves the group's own rule (built here, never sent in)."""
    facts = _facts(session, actor)
    rules = _rules(session, actor)
    handled = _handled(facts, _marks(session, actor), rules, today)
    mine = {f.item_id for f in facts}
    wanted = [i for i in dict.fromkeys(req.item_ids) if i in mine and i not in handled]
    label, rule_selector = "手动标记", None
    if req.group_key:
        open_ = [f for f in facts if not f.seen and f.item_id not in handled]
        found = next(
            (
                g
                for g in group(open_, today, integrations.course_codes(session, actor), facts)
                if g.key == req.group_key
            ),
            None,
        )
        if found is None:
            raise Conflict("这一组已经没有未处理的邮件了")
        in_group = set(found.item_ids)
        wanted = [i for i in wanted if i in in_group]
        label, rule_selector = found.label[:80], found.rule
    if req.save_rule and rule_selector is None:
        raise Invalid("这一组不能保存成规则")
    if not wanted:
        raise Conflict("这些邮件已经处理过了")

    def op() -> audit.Outcome[TriageBatch]:
        batch = TriageBatchRow(
            owner_id=actor.owner_id,
            source=actor.source,
            version=1,
            kind="group" if req.group_key else "manual",
            status=BatchStatus.applied.value,
            label=label,
            group_key=req.group_key,
            applied_ids=wanted,
            applied_at=now,
        )
        session.add(batch)
        session.flush()
        for item_id in wanted:
            _set(session, actor, item_id, HANDLED, batch.id)
        selector_json = rule_selector.model_dump(mode="json") if rule_selector else None
        already = any(r.enabled and r.selector == selector_json for r in rules)
        if req.save_rule and selector_json is not None and not already:
            rule = TriageRuleRow(
                owner_id=actor.owner_id,
                source=actor.source,
                version=1,
                name=label,
                selector=selector_json,
                enabled=True,
                from_batch_id=batch.id,
            )
            session.add(rule)
            session.flush()
            batch.rule_id = rule.id
        session.flush()
        return audit.Outcome(batch.id, _batch(batch), {"count": len(wanted), "rule": batch.rule_id})

    # The group's kind only: a key like "sender:<domain>" says who mails the user.
    kind = req.group_key.split(":", 1)[0]
    detail: dict[str, Any] = {"group": kind, "save_rule": req.save_rule}
    return audit.audited(session, actor, "triage_batch", "apply", None, detail, op)


def undo(session: Session, actor: Actor, batch_id: str, now: datetime) -> TriageBatch:
    batch = session.get(TriageBatchRow, batch_id)
    if batch is None or batch.owner_id != actor.owner_id:
        raise NotFound("没有这次操作")
    if batch.status != BatchStatus.applied.value:
        raise Conflict("这次操作已经撤销过了")

    def op() -> audit.Outcome[TriageBatch]:
        restored = 0
        for row in session.scalars(
            select(MailTriageStateRow).where(
                MailTriageStateRow.owner_id == actor.owner_id,
                MailTriageStateRow.batch_id == batch.id,
            )
        ):
            row.state, row.prev_state, row.batch_id = row.prev_state, row.state, None
            restored += 1
        if batch.rule_id:
            rule = session.get(TriageRuleRow, batch.rule_id)
            if rule is not None and rule.owner_id == actor.owner_id:
                rule.enabled = False
        batch.status, batch.undone_at = BatchStatus.undone.value, now
        session.flush()
        return audit.Outcome(batch.id, _batch(batch), {"restored": restored})

    return audit.audited(session, actor, "triage_batch", "undo", batch_id, {}, op)


def set_item(session: Session, actor: Actor, item_id: str, handled: bool) -> HandledMark:
    """One mail by hand: 已处理, or back to 未处理 even if a rule matches it."""
    if item_id not in {h.id for h in integrations.item_heads(session, actor, EMAIL)}:
        raise NotFound("没有这封邮件")

    def op() -> audit.Outcome[HandledMark]:
        _set(session, actor, item_id, HANDLED if handled else UNHANDLED, None)
        session.flush()
        mark = HandledMark(item_id=item_id, by=HandledBy.manual, batch_id=None, rule_id=None)
        return audit.Outcome(item_id, mark, {"handled": handled})

    return audit.audited(session, actor, "mail_triage_state", "set", item_id, {}, op)


def set_rule_enabled(
    session: Session, actor: Actor, rule_id: str, enabled: bool, today: date
) -> TriageRule:
    rule = session.get(TriageRuleRow, rule_id)
    if rule is None or rule.owner_id != actor.owner_id:
        raise NotFound("没有这条规则")

    def op() -> audit.Outcome[TriageRule]:
        rule.enabled = enabled
        session.flush()
        marks = _handled(_facts(session, actor), _marks(session, actor), [rule], today)
        matched = sum(1 for m in marks.values() if m.rule_id == rule.id)
        return audit.Outcome(rule.id, _rule(rule, matched), {"enabled": enabled})

    return audit.audited(session, actor, "triage_rule", "update", rule_id, {}, op)


def handled_ids(session: Session, actor: Actor, today: date) -> set[str]:
    """Mails counted as 已处理 now (an explicit mark, or a matching enabled rule)."""
    facts = _facts(session, actor)
    return set(_handled(facts, _marks(session, actor), _rules(session, actor), today))


__all__ = ["handle", "handled_ids", "set_item", "set_rule_enabled", "undo", "view"]
