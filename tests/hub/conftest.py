from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.hub.core.settings import Settings
from tests.hub.support import hub_client


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(data_dir: Path) -> Iterator[TestClient]:
    with hub_client(Settings(data_dir=data_dir)) as c:
        yield c
