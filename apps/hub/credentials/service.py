"""Integration secrets: the value in a SecretStore (keyring), metadata in SQLite (ADR 0018).

Nothing here returns a secret to an HTTP client. Hub modules (job handlers) get one with
`reveal`, and every use is audited.
"""

import contextlib
import logging
import threading
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.core.domain import Actor, Conflict, Invalid, NotFound
from apps.hub.credentials.models import CredentialRow
from packages.contracts.credentials import Credential

logger = logging.getLogger(__name__)

ENTITY = "credential"
# One process (ADR 0014): this lock keeps a store write and its row write together,
# so two requests for the same name cannot interleave.
_WRITE_LOCK = threading.Lock()


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, secret: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringSecretStore:
    """Windows Credential Manager, one entry per secret under `service`."""

    def __init__(self, service: str) -> None:
        self.service = service

    def get(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(self.service, key)

    def set(self, key: str, secret: str) -> None:
        import keyring

        try:
            keyring.set_password(self.service, key, secret)
        except Exception as exc:
            # The backend's error says nothing secret, but the caller only needs to know
            # the store refused (e.g. over Credential Manager's size limit).
            raise Invalid(
                f"Windows Credential Manager refused the secret ({type(exc).__name__})"
            ) from None

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with contextlib.suppress(PasswordDeleteError):  # already gone
            keyring.delete_password(self.service, key)


class MemorySecretStore:
    """For tests, and for machines without a keyring backend."""

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.secrets.get(key)

    def set(self, key: str, secret: str) -> None:
        self.secrets[key] = secret

    def delete(self, key: str) -> None:
        self.secrets.pop(key, None)


def _key(actor: Actor, name: str) -> str:
    return f"{actor.owner_id}:{name}"


def _read(row: CredentialRow) -> Credential:
    return Credential.model_validate(row, from_attributes=True)


def _find(session: Session, actor: Actor, name: str) -> CredentialRow | None:
    return session.scalars(
        select(CredentialRow).where(
            CredentialRow.owner_id == actor.owner_id, CredentialRow.name == name
        )
    ).one_or_none()


def put(
    session: Session, actor: Actor, store: SecretStore, name: str, secret: str, note: str
) -> Credential:
    """Set or replace a secret. The store is written first: if the database write then
    fails, the new value is already in place and the old metadata still describes it."""

    created = False

    def op() -> audit.Outcome[Credential]:
        nonlocal created
        row = _find(session, actor, name)
        created = row is None
        store.set(_key(actor, name), secret)
        if row is None:
            row = CredentialRow(owner_id=actor.owner_id, source=actor.source, name=name)
            session.add(row)
        row.note = note
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict(f"credential {name} is being written concurrently") from exc
        return audit.Outcome(row.id, _read(row), {"replaced": not created})

    with _WRITE_LOCK:
        try:
            # Only the name goes to the audit log, never the value or its length or hash.
            return audit.audited(session, actor, ENTITY, "put", None, {"name": name}, op)
        except Exception:
            if created:
                # No row will point at the new secret: take it back out of the store, or
                # the user could neither see nor delete it through the Hub.
                try:
                    store.delete(_key(actor, name))
                except Exception:
                    logger.exception("could not remove the orphaned secret for %s", name)
            raise


def delete(session: Session, actor: Actor, store: SecretStore, name: str) -> None:
    """Remove the secret from the store, then its metadata."""

    def op() -> audit.Outcome[None]:
        row = _find(session, actor, name)
        if row is None:
            raise NotFound(f"credential {name} not found")
        store.delete(_key(actor, name))
        session.delete(row)
        session.flush()
        return audit.Outcome(row.id, None)

    with _WRITE_LOCK:
        audit.audited(session, actor, ENTITY, "delete", None, {"name": name}, op)


def list_all(session: Session, actor: Actor) -> list[Credential]:
    rows = session.scalars(
        select(CredentialRow)
        .where(CredentialRow.owner_id == actor.owner_id)
        .order_by(CredentialRow.name)
    )
    return [_read(r) for r in rows]


def reveal(session: Session, actor: Actor, store: SecretStore, name: str) -> str:
    """The secret, for Hub code only (never an HTTP response). Each use is audited.

    Like every audited call, this commits `session` (or rolls it back on NotFound), so
    pass a session with no pending work of the caller's own.
    """

    def op() -> audit.Outcome[str]:
        row = _find(session, actor, name)
        secret = None if row is None else store.get(_key(actor, name))
        if row is None or secret is None:
            raise NotFound(f"credential {name} is not set; enter it again")
        row.last_used_at = datetime.now(UTC)
        session.flush()
        return audit.Outcome(row.id, secret)

    return audit.audited(session, actor, ENTITY, "use", None, {"name": name}, op)
