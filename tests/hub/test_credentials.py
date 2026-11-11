import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.hub.audit import service as audit
from apps.hub.backup.service import export_data
from apps.hub.core.db import DB_FILENAME
from apps.hub.core.domain import Actor, Conflict, NotFound
from apps.hub.core.settings import Settings
from apps.hub.credentials import service
from apps.hub.credentials.models import CredentialRow
from tests.hub.support import hub_client

SECRET = "canvas-7f3K9-very-secret-token"
OWNER = Actor(owner_id="local", source="test")


@pytest.fixture
def store() -> service.MemorySecretStore:
    return service.MemorySecretStore()


@pytest.fixture
def client(data_dir: Path, store: service.MemorySecretStore) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir, jobs_enabled=False), secret_store=store) as c:
        yield c


def put(client: TestClient, name: str, secret: str = SECRET, note: str = "") -> object:
    return client.put(f"/credentials/{name}", json={"secret": secret, "note": note})


def reveal(client: TestClient, store: service.SecretStore, name: str) -> str:
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        return service.reveal(s, OWNER, store, name)


def test_the_secret_goes_to_the_store_and_only_metadata_to_sqlite(
    client: TestClient, store: service.MemorySecretStore
) -> None:
    created = put(client, "canvas.token", note="school Canvas")
    assert created.status_code == 200  # type: ignore[attr-defined]
    body = created.json()  # type: ignore[attr-defined]
    assert body["name"] == "canvas.token" and body["note"] == "school Canvas"
    assert SECRET not in json.dumps(body)
    assert store.secrets == {"local:canvas.token": SECRET}
    (listed,) = client.get("/credentials").json()
    assert listed["name"] == "canvas.token" and SECRET not in json.dumps(listed)


def test_no_route_returns_a_secret(client: TestClient) -> None:
    put(client, "canvas.token")
    assert client.get("/credentials/canvas.token").status_code in (404, 405)
    paths = client.get("/openapi.json").json()["paths"]
    exposed = {(path, method) for path, ops in paths.items() for method in ops}
    assert {(p, m) for p, m in exposed if p.startswith("/credentials")} == {
        ("/credentials", "get"),
        ("/credentials/{name}", "put"),
        ("/credentials/{name}", "delete"),
    }
    assert "secret" not in json.dumps(paths["/credentials"]["get"]["responses"])


def test_the_secret_is_in_no_table_audit_row_log_or_export(
    client: TestClient, data_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        put(client, "canvas.token")
        put(client, "canvas.token", secret=SECRET + "-v2")
        reveal(client, client.app.state.secret_store, "canvas.token")  # type: ignore[attr-defined]
    stored = b"".join(p.read_bytes() for p in data_dir.glob(f"{DB_FILENAME}*"))
    assert SECRET.encode() not in stored
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        events = audit.list_events(s, "local")
    assert SECRET not in json.dumps([e.model_dump(mode="json") for e in events])
    assert SECRET not in caplog.text
    package = tmp_path / "export.zip"
    export_data(data_dir, package)
    with zipfile.ZipFile(package) as z:
        assert not any(SECRET.encode() in z.read(n) for n in z.namelist())


def test_overwrite_and_delete(client: TestClient, store: service.MemorySecretStore) -> None:
    put(client, "mail.password", secret="first")
    put(client, "mail.password", secret="second")
    assert store.secrets == {"local:mail.password": "second"}
    assert len(client.get("/credentials").json()) == 1
    assert client.delete("/credentials/mail.password").status_code == 204
    assert store.secrets == {}
    assert client.get("/credentials").json() == []
    assert client.delete("/credentials/mail.password").status_code == 404


@pytest.mark.parametrize("name", ["Canvas", "-x", "a b", "x" * 81, "abc%0A", "abc%00"])
def test_a_bad_name_is_refused(client: TestClient, name: str) -> None:
    assert put(client, name).status_code == 422  # type: ignore[attr-defined]


@pytest.mark.parametrize("path", ["a/b", "token%2Fx", ".."])
def test_a_name_that_is_not_one_path_segment_matches_no_route(
    client: TestClient, path: str
) -> None:
    assert put(client, path).status_code in (404, 405)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "body",
    [
        {"secret": SECRET * 60},  # too long for Credential Manager
        {"secrets": SECRET},  # a typo in the field name
        {"secret": "s", "password": SECRET},  # an unexpected field
        {"secret": [SECRET]},  # not a string
        {"secret": ""},
    ],
)
def test_a_refused_body_never_echoes_the_secret(
    client: TestClient, store: service.MemorySecretStore, body: dict[str, object]
) -> None:
    response = client.put("/credentials/x", json=body)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert store.secrets == {}


def test_the_longest_secret_credential_manager_holds_is_accepted(
    client: TestClient, store: service.MemorySecretStore
) -> None:
    key = "\U0001f511"  # outside the BMP: two UTF-16 units each
    assert put(client, "long", secret="a" * 1280).status_code == 200  # type: ignore[attr-defined]
    assert put(client, "longer", secret="a" * 1281).status_code == 422  # type: ignore[attr-defined]
    assert put(client, "emoji", secret=key * 641).status_code == 422  # type: ignore[attr-defined]
    assert list(store.secrets) == ["local:long"]


class FailingRowStore(service.MemorySecretStore):
    """Accepts the secret, then makes the database write fail, as a full disk would."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def set(self, key: str, secret: str) -> None:
        super().set(key, secret)
        # A second row with the same name breaks the unique constraint at flush.
        self.session.add(CredentialRow(owner_id="local", source="test", name="canvas.token"))


def test_a_failed_create_leaves_no_orphan_secret(client: TestClient) -> None:
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        store = FailingRowStore(s)
        with pytest.raises(Conflict):
            service.put(s, OWNER, store, "canvas.token", SECRET, "")
    assert store.secrets == {}
    assert client.get("/credentials").json() == []


def test_reveal_gives_hub_code_the_secret_and_audits_the_use(
    client: TestClient, store: service.MemorySecretStore
) -> None:
    put(client, "canvas.token")
    assert reveal(client, store, "canvas.token") == SECRET
    (listed,) = client.get("/credentials").json()
    assert listed["last_used_at"] is not None
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        actions = [(e.action, e.result) for e in audit.list_events(s, "local")]
    assert actions == [("credential.put", "ok"), ("credential.use", "ok")]


def test_reveal_of_an_unknown_deleted_or_vanished_secret_is_not_found(
    client: TestClient, store: service.MemorySecretStore
) -> None:
    with pytest.raises(NotFound):
        reveal(client, store, "never.set")
    put(client, "gone")
    client.delete("/credentials/gone")
    with pytest.raises(NotFound):
        reveal(client, store, "gone")
    put(client, "vanished")
    store.secrets.clear()  # e.g. the user cleaned up Credential Manager by hand
    with pytest.raises(NotFound, match="enter it again"):
        reveal(client, store, "vanished")


def test_credentials_belong_to_their_owner(
    client: TestClient, store: service.MemorySecretStore
) -> None:
    put(client, "canvas.token")
    other = Actor(owner_id="someone-else")
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        assert service.list_all(s, other) == []
        with pytest.raises(NotFound):
            service.reveal(s, other, store, "canvas.token")


def test_each_write_is_audited_once_by_name_only(client: TestClient) -> None:
    put(client, "canvas.token")
    put(client, "canvas.token", secret="again")
    client.delete("/credentials/canvas.token")
    client.delete("/credentials/canvas.token")
    with Session(client.app.state.engine) as s:  # type: ignore[attr-defined]
        events = audit.list_events(s, "local")
    assert [(e.action, e.result) for e in events] == [
        ("credential.put", "ok"),
        ("credential.put", "ok"),
        ("credential.delete", "ok"),
        ("credential.delete", "not_found"),
    ]
    assert all(e.detail.get("name") == "canvas.token" for e in events)
    assert [e.detail.get("replaced") for e in events[:2]] == [False, True]
