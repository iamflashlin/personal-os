from pathlib import Path

from fastapi.testclient import TestClient

from apps.hub.core.settings import Settings
from apps.hub.credentials.service import MemorySecretStore, SecretStore
from apps.hub.main import create_app


def hub_client(
    settings: Settings,
    web_dist: Path | None = None,
    secret_store: SecretStore | None = None,
) -> TestClient:
    """A TestClient that talks to the Hub as http://127.0.0.1 (allowed by its Host check).

    The built web UI is off unless a `web_dist` is given, so results do not depend on
    whether `apps/web/dist` happens to exist on this machine. Secrets go to an in-memory
    store, never to this machine's Credential Manager.
    """
    app = create_app(settings, web_dist=web_dist, secret_store=secret_store or MemorySecretStore())
    return TestClient(app, base_url="http://127.0.0.1")
