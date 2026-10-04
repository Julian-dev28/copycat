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


def test_add_leader_409_at_the_cap(client: TestClient, auth_headers: dict) -> None:
    from contracts.models import MAX_LEADERS
    for i in range(MAX_LEADERS):
        addr = "0x" + f"{i:040x}"
        r = client.post("/api/leaders", headers=auth_headers, json={"address": addr})
        assert r.status_code == 200, r.text

    eleventh = "0x" + "f" * 40
    r = client.post("/api/leaders", headers=auth_headers, json={"address": eleventh})
    assert r.status_code == 409

    body = client.get("/api/settings", headers=auth_headers).json()
    assert len(body["leaders"]) == MAX_LEADERS
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


# ── our own account is never a leader ───────────────────────────────────────

from api_fakes import OUR_ADDRESS  # noqa: E402


def test_add_leader_rejects_our_own_address(client, auth_headers) -> None:
    r = client.post("/api/leaders", headers=auth_headers, json={"address": OUR_ADDRESS.upper().replace("0X", "0x")})
    assert r.status_code == 400 and "own account" in r.json()["detail"]


def test_patch_and_put_reject_our_own_address_in_leaders(client, auth_headers) -> None:
    r = client.patch("/api/settings", headers=auth_headers, json={"leaders": [OUR_ADDRESS]})
    assert r.status_code == 400
    full = client.get("/api/settings", headers=auth_headers).json()
    full["leaders"] = [OUR_ADDRESS]
    assert client.put("/api/settings", headers=auth_headers, json=full).status_code == 400
    assert client.get("/api/settings", headers=auth_headers).json()["leaders"] == []
