from __future__ import annotations

from fastapi.testclient import TestClient

from api.deps import get_engine_client
from contracts.models import EngineEvent

from api_fakes import FakeEngineClient, UnavailableEngineClient


def test_get_status(client: TestClient, auth_headers: dict, fake_engine: FakeEngineClient) -> None:
    r = client.get("/api/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["enabled"] is False
    assert body["dry_run"] is True


def test_get_events_limit_and_order(
    client: TestClient, auth_headers: dict, fake_engine: FakeEngineClient
) -> None:
    fake_engine.event_log.extend(
        [
            EngineEvent(ts_ms=100, action="open", coin="BTC"),
            EngineEvent(ts_ms=200, action="add", coin="BTC"),
            EngineEvent(ts_ms=300, action="close", coin="BTC"),
        ]
    )
    r = client.get("/api/events", headers=auth_headers, params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert [e["ts_ms"] for e in body] == [300, 200]  # newest first


def test_get_events_since_ms_filters(
    client: TestClient, auth_headers: dict, fake_engine: FakeEngineClient
) -> None:
    fake_engine.event_log.extend(
        [
            EngineEvent(ts_ms=100, action="open", coin="BTC"),
            EngineEvent(ts_ms=200, action="add", coin="BTC"),
        ]
    )
    r = client.get("/api/events", headers=auth_headers, params={"since_ms": 150})
    assert r.status_code == 200
    body = r.json()
    assert [e["ts_ms"] for e in body] == [200]


def test_status_503_when_engine_unavailable(client: TestClient, auth_headers: dict, app) -> None:
    app.dependency_overrides[get_engine_client] = lambda: UnavailableEngineClient()
    r = client.get("/api/status", headers=auth_headers)
    assert r.status_code == 503


def test_events_503_when_engine_unavailable(client: TestClient, auth_headers: dict, app) -> None:
    app.dependency_overrides[get_engine_client] = lambda: UnavailableEngineClient()
    r = client.get("/api/events", headers=auth_headers)
    assert r.status_code == 503


def test_halt_flips_enabled_false_and_persists(client: TestClient, auth_headers: dict) -> None:
    client.patch("/api/settings", headers=auth_headers, json={"enabled": True})
    r = client.post("/api/engine/halt", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = client.get("/api/settings", headers=auth_headers)
    assert r.json()["enabled"] is False
