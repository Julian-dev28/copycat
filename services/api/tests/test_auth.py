from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.config import Config
from api.deps import get_engine_client
from api.main import create_app

from api_fakes import FakeEngineClient


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


def test_no_token_configured_still_requires_one(data_dir: Path) -> None:
    """There is no unauthenticated dev mode any more, even on 127.0.0.1: a
    token is generated into data/api_token and required on every route."""
    config = Config(data_dir=data_dir, api_token=None, bind="127.0.0.1",
                    allowed_hosts=["testserver"])
    app = create_app(config)
    app.dependency_overrides[get_engine_client] = lambda: FakeEngineClient()
    client = TestClient(app)

    assert client.get("/api/settings").status_code == 401
    token = (data_dir / "api_token").read_text().strip()
    r = client.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_foreign_host_header_is_rejected_dns_rebinding(client: TestClient, auth_headers: dict) -> None:
    r = client.patch("/api/settings", headers={**auth_headers, "Host": "evil.com:8787"},
                     json={"enabled": True})
    assert r.status_code == 400
    assert client.get("/api/health", headers={"Host": "evil.com"}).status_code == 400


def test_localhost_host_header_with_port_is_allowed(client: TestClient, auth_headers: dict) -> None:
    r = client.get("/api/settings", headers={**auth_headers, "Host": "localhost:8787"})
    assert r.status_code == 200
