from __future__ import annotations

from fastapi.testclient import TestClient

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def test_add_leader(client: TestClient, auth_headers: dict) -> None:
    r = client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A})
    assert r.status_code == 200
    assert r.json()["leaders"] == [ADDR_A]


def test_add_leader_bad_address_400(client: TestClient, auth_headers: dict) -> None:
    r = client.post("/api/leaders", headers=auth_headers, json={"address": "not-an-address"})
    assert r.status_code == 400

    r = client.post("/api/leaders", headers=auth_headers, json={"address": "0x" + "a" * 39})
    assert r.status_code == 400


def test_add_leader_is_idempotent(client: TestClient, auth_headers: dict) -> None:
    client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A})
    r = client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A.upper()})
    assert r.status_code == 200
    assert r.json()["leaders"] == [ADDR_A]  # not duplicated, address normalized


def test_add_leader_409_at_ten(client: TestClient, auth_headers: dict) -> None:
    for i in range(10):
        addr = "0x" + f"{i:040x}"
        r = client.post("/api/leaders", headers=auth_headers, json={"address": addr})
        assert r.status_code == 200, r.text

    eleventh = "0x" + "f" * 40
    r = client.post("/api/leaders", headers=auth_headers, json={"address": eleventh})
    assert r.status_code == 409

    body = client.get("/api/settings", headers=auth_headers).json()
    assert len(body["leaders"]) == 10
    assert eleventh not in body["leaders"]


def test_delete_leader_also_drops_its_override(client: TestClient, auth_headers: dict) -> None:
    client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A})
    client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 5}}},
    )
    r = client.delete(f"/api/leaders/{ADDR_A}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert ADDR_A not in body["leaders"]
    assert ADDR_A not in body["leader_overrides"]


def test_delete_leader_not_present_is_idempotent(client: TestClient, auth_headers: dict) -> None:
    r = client.delete(f"/api/leaders/{ADDR_B}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["leaders"] == []
