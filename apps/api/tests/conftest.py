# ruff: noqa: E402  (env vars must be set before importing the app)
import os
import tempfile
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="factory-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.sqlite"
os.environ["DATA_DIR"] = str(Path(_tmpdir) / "data")
os.environ["APP_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

import pytest
from factory_api.db import Base, engine
from factory_api.main import app
from fastapi.testclient import TestClient

Base.metadata.create_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_client(client):
    resp = client.post("/api/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200
    return client
