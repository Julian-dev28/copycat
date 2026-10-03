from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.config import Config
from api.deps import get_discovery_client, get_engine_client
from api.main import create_app

from api_fakes import FakeDiscoveryClient, FakeEngineClient


def test_rejects_missing_token(client: TestClient) -> None:
    r = client.get("/api/settings")
    assert r.status_code == 401


def test_rejects_wrong_token(client: TestClient) -> None:
    r = client.get("/api/settings", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_rejects_non_bearer_scheme(client: TestClient, auth_headers: dict) -> None:
    token = auth_headers["Authorization"].split(" ")[1]
    r = client.get("/api/settings", headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 401


def test_accepts_correct_token(client: TestClient, auth_headers: dict) -> None:
    r = client.get("/api/settings", headers=auth_headers)
    assert r.status_code == 200


def test_health_needs_no_token_either_way(client: TestClient, auth_headers: dict) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers=auth_headers).status_code == 200


def test_auth_off_when_no_token_configured(data_dir: Path) -> None:
    """COPYCAT_BIND=127.0.0.1 with no token is the documented localhost-only
    dev mode: every route works with no Authorization header at all.
    """
    config = Config(data_dir=data_dir, api_token=None, bind="127.0.0.1")
    app = create_app(config)
    app.dependency_overrides[get_engine_client] = lambda: FakeEngineClient()
    app.dependency_overrides[get_discovery_client] = lambda: FakeDiscoveryClient()
    client = TestClient(app)

    r = client.get("/api/settings")
    assert r.status_code == 200
    r = client.get("/api/status")
    assert r.status_code == 200
