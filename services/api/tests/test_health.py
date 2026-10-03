from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok_without_auth(client: TestClient) -> None:
    """GET /api/health is exempt from auth even though a token is
    configured -- docs/ARCHITECTURE.md: "on every route except
    GET /api/health".
    """
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["version"], str) and body["version"]
