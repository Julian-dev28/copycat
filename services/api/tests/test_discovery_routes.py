from __future__ import annotations

from fastapi.testclient import TestClient

from api.deps import get_discovery_client

from api_fakes import FakeDiscoveryClient, UnavailableDiscoveryClient


def test_start_run_uses_current_settings_when_none_given(
    client: TestClient, auth_headers: dict, fake_discovery: FakeDiscoveryClient
) -> None:
    client.patch("/api/settings", headers=auth_headers, json={"dry_run": False})
    r = client.post(
        "/api/discovery/runs",
        headers=auth_headers,
        json={"sim_equity_usd": 1000.0, "top_n": 5},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert run_id in fake_discovery.runs
    settings_used, sim_equity, top_n = fake_discovery.calls[0]
    assert settings_used.dry_run is False
    assert sim_equity == 1000.0
    assert top_n == 5


def test_start_run_uses_provided_settings_override(
    client: TestClient, auth_headers: dict, fake_discovery: FakeDiscoveryClient
) -> None:
    current = client.get("/api/settings", headers=auth_headers).json()
    current["dry_run"] = False
    current["leverage"] = 3
    r = client.post(
        "/api/discovery/runs",
        headers=auth_headers,
        json={"sim_equity_usd": 500.0, "top_n": 3, "settings": current},
    )
    assert r.status_code == 200
    settings_used, _, _ = fake_discovery.calls[0]
    assert settings_used.leverage == 3
    assert settings_used.dry_run is False
    # the override must not have been written to disk; only /api/settings writes
    stored = client.get("/api/settings", headers=auth_headers).json()
    assert stored["leverage"] != 3


def test_get_latest_run_404_when_none(
    client: TestClient, auth_headers: dict, fake_discovery: FakeDiscoveryClient
) -> None:
    r = client.get("/api/discovery/runs/latest", headers=auth_headers)
    assert r.status_code == 404


def test_get_latest_run(client: TestClient, auth_headers: dict, fake_discovery: FakeDiscoveryClient) -> None:
    client.post(
        "/api/discovery/runs", headers=auth_headers, json={"sim_equity_usd": 100.0, "top_n": 1}
    )
    r = client.get("/api/discovery/runs/latest", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sim_equity_usd"] == 100.0


def test_get_run_by_id(client: TestClient, auth_headers: dict, fake_discovery: FakeDiscoveryClient) -> None:
    created = client.post(
        "/api/discovery/runs", headers=auth_headers, json={"sim_equity_usd": 50.0, "top_n": 2}
    ).json()
    run_id = created["run_id"]
    r = client.get(f"/api/discovery/runs/{run_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id


def test_get_run_by_id_404_when_unknown(client: TestClient, auth_headers: dict) -> None:
    r = client.get("/api/discovery/runs/does-not-exist", headers=auth_headers)
    assert r.status_code == 404


def test_discovery_503_when_unavailable(client: TestClient, auth_headers: dict, app) -> None:
    app.dependency_overrides[get_discovery_client] = lambda: UnavailableDiscoveryClient()
    r = client.post(
        "/api/discovery/runs", headers=auth_headers, json={"sim_equity_usd": 100.0, "top_n": 1}
    )
    assert r.status_code == 503
    r = client.get("/api/discovery/runs/latest", headers=auth_headers)
    assert r.status_code == 503
    r = client.get("/api/discovery/runs/abc", headers=auth_headers)
    assert r.status_code == 503
