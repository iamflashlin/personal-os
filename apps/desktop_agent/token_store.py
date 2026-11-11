"""Where the agent keeps its one durable secret: the device token (HANDOFF §4.6)."""

import contextlib
from typing import Protocol

USERNAME = "device-token"


class TokenStore(Protocol):
    def get(self) -> str | None: ...
    def set(self, token: str) -> None: ...
    def delete(self) -> None: ...


class KeyringTokenStore:
    """Windows Credential Manager through `keyring`; nothing is written to disk by us."""

    def __init__(self, service: str) -> None:
        self.service = service

    def get(self) -> str | None:
        import keyring

        return keyring.get_password(self.service, USERNAME)

    def set(self, token: str) -> None:
        import keyring

        keyring.set_password(self.service, USERNAME, token)

    def delete(self) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with contextlib.suppress(PasswordDeleteError):  # already gone
            keyring.delete_password(self.service, USERNAME)


class MemoryTokenStore:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get(self) -> str | None:
        return self.token

    def set(self, token: str) -> None:
        self.token = token

    def delete(self) -> None:
        self.token = None
