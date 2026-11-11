"""Session-wide guards for every test."""

from collections.abc import Iterator

import keyring
import pytest
from keyring.backends import fail


@pytest.fixture(autouse=True, scope="session")
def no_real_credential_manager() -> Iterator[None]:
    """Tests must never read or write this PC's Windows Credential Manager (ADR 0018).

    Tests use in-memory stores; any code path that still reaches keyring fails loudly.
    Only the verify scripts use the real store, under throwaway service names.
    """
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)
