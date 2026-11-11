"""Pairing and tokens for desktop agents (ADR 0014).

A pairing code and a token are each shown once. The Hub stores only their SHA-256, so
neither the database nor the audit log can give them back.
"""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Forbidden, NotFound
from apps.hub.devices.links import AgentLink, AgentLinks
from apps.hub.devices.models import DeviceRow, PairingCodeRow
from packages.contracts.actions import ActionResult
from packages.contracts.devices import (
    TOKEN_PREFIX,
    Device,
    PairingCode,
    PairRequest,
    PairResponse,
)

__all__ = ["AgentHooks", "AgentLink", "AgentLinks"]

ENTITY = "device"
PAIRING_TTL = timedelta(minutes=5)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class AgentHooks:
    """What another module does when an agent reports a result or its socket drops.

    `main` wires these to the actions module, so devices never imports actions.
    """

    on_result: Callable[[Session, Actor, ActionResult], None]
    on_lost: Callable[[Session, Actor, set[str]], None]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _read(row: DeviceRow) -> Device:
    return Device.model_validate(row, from_attributes=True)


def _get_row(session: Session, actor: Actor, device_id: str) -> DeviceRow:
    row = session.get(DeviceRow, device_id)
    if row is None or row.owner_id != actor.owner_id:
        raise NotFound(f"device {device_id} not found")
    return row


def create_pairing_code(session: Session, actor: Actor) -> PairingCode:
    raw = "".join(secrets.choice(_CROCKFORD) for _ in range(8))
    expires_at = _now() + PAIRING_TTL

    def op() -> audit.Outcome[PairingCode]:
        row = PairingCodeRow(
            owner_id=actor.owner_id,
            source=actor.source,
            code_hash=_sha256(raw),
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        shown = PairingCode(code=f"{raw[:4]}-{raw[4:]}", expires_at=expires_at)
        return audit.Outcome(row.id, shown, {"expires_at": expires_at.isoformat()})

    return audit.audited(session, actor, "pairing_code", "create", None, {}, op)


def pair(session: Session, actor: Actor, request: PairRequest) -> PairResponse:
    """Trade a valid, unused, unexpired code for a new device and its token."""
    code_hash = _sha256(request.code.replace("-", ""))
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)

    def op() -> audit.Outcome[PairResponse]:
        code = session.scalars(
            select(PairingCodeRow).where(
                PairingCodeRow.owner_id == actor.owner_id,
                PairingCodeRow.code_hash == code_hash,
            )
        ).one_or_none()
        if code is None or code.used_at is not None or code.expires_at <= _now():
            # One message for all three, so a caller learns nothing about which codes exist.
            raise Forbidden("pairing code is invalid, used or expired")
        device = DeviceRow(
            owner_id=actor.owner_id,
            source=actor.source,
            name=request.device_name,
            platform=request.platform,
            token_hash=_sha256(token),
        )
        session.add(device)
        session.flush()
        code.used_at = _now()
        code.device_id = device.id
        return audit.Outcome(device.id, PairResponse(device_id=device.id, token=token))

    detail = {"device_name": request.device_name, "platform": request.platform}
    return audit.audited(session, actor, ENTITY, "pair", None, detail, op)


def list_devices(session: Session, actor: Actor) -> list[Device]:
    rows = session.scalars(
        select(DeviceRow)
        .where(DeviceRow.owner_id == actor.owner_id)
        .order_by(DeviceRow.created_at, DeviceRow.id)
    ).all()
    return [_read(r) for r in rows]


def revoke(session: Session, actor: Actor, device_id: str) -> Device:
    """Revoke the device's token. Revoking twice keeps the first revocation time."""

    def op() -> audit.Outcome[Device]:
        row = _get_row(session, actor, device_id)
        if row.revoked_at is not None:
            return audit.Outcome(row.id, _read(row), result="unchanged")
        row.revoked_at = _now()
        session.flush()
        return audit.Outcome(row.id, _read(row))

    return audit.audited(session, actor, ENTITY, "revoke", device_id, {}, op)


def authenticate(session: Session, owner_id: str, token: str) -> Device | None:
    """The live, unrevoked device this token belongs to, or None."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    row = session.scalars(
        select(DeviceRow).where(
            DeviceRow.owner_id == owner_id, DeviceRow.token_hash == _sha256(token)
        )
    ).one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    return _read(row)


def record_connection(session: Session, actor: Actor, device_id: str, *, connected: bool) -> None:
    """Note a connect or disconnect on the device row; heartbeats are not recorded."""

    def op() -> audit.Outcome[None]:
        row = _get_row(session, actor, device_id)
        if connected:
            row.last_connected_at = _now()
        else:
            row.last_disconnected_at = _now()
        session.flush()
        return audit.Outcome(row.id, None)

    action = "connect" if connected else "disconnect"
    audit.audited(session, actor, ENTITY, action, device_id, {}, op)
