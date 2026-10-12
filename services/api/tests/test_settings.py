from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.config import Config

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def test_get_settings_serves_defaults_when_file_missing(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    assert not config.data_dir.joinpath("settings.json").exists()
    r = client.get("/api/settings", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["dry_run"] is True
    assert body["leaders"] == []
    # reading must not create the file
    assert not config.data_dir.joinpath("settings.json").exists()


def test_put_full_settings_persists_and_is_atomic(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    r = client.get("/api/settings", headers=auth_headers)
    full = r.json()
    full["dry_run"] = False
    full["leverage"] = 5
    full["poll_interval_s"] = 10.0

    r = client.put("/api/settings", headers=auth_headers, json=full)
    assert r.status_code == 200
    assert r.json()["dry_run"] is False
    assert r.json()["leverage"] == 5

    settings_path = config.data_dir / "settings.json"
    assert settings_path.exists()
    on_disk = json.loads(settings_path.read_text())
    assert on_disk["dry_run"] is False
    assert on_disk["leverage"] == 5
    # no leftover temp files from the atomic write
    assert list(config.data_dir.glob(".settings-*.tmp")) == []


def test_put_invalid_full_settings_422_and_file_untouched(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    r = client.get("/api/settings", headers=auth_headers)
    full = r.json()
    full["leverage"] = 999  # ge=1, le=50

    r = client.put("/api/settings", headers=auth_headers, json=full)
    assert r.status_code == 422
    assert not (config.data_dir / "settings.json").exists()


def test_patch_shallow_merges_top_level_fields(client: TestClient, auth_headers: dict) -> None:
    r = client.patch("/api/settings", headers=auth_headers, json={"dry_run": False})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is False
    # untouched fields keep their defaults
    assert body["enabled"] is False
    assert body["leverage"] == 20

    r = client.patch("/api/settings", headers=auth_headers, json={"leverage": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["leverage"] == 7
    assert body["dry_run"] is False  # the earlier PATCH's change survived


def test_patch_leader_override_sets_and_replaces(client: TestClient, auth_headers: dict) -> None:
    r = client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 5, "sizing_mode": "fixed_notional"}}},
    )
    assert r.status_code == 200
    ov = r.json()["leader_overrides"][ADDR_A]
    assert ov["leverage"] == 5
    assert ov["sizing_mode"] == "fixed_notional"

    # a second PATCH for the same leader REPLACES the whole override, not
    # merges: sizing_mode must be gone (back to null/inherit), not retained.
    r = client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 9}}},
    )
    assert r.status_code == 200
    ov = r.json()["leader_overrides"][ADDR_A]
    assert ov["leverage"] == 9
    assert ov["sizing_mode"] is None


def test_patch_leader_override_null_clears_it(client: TestClient, auth_headers: dict) -> None:
    client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 5}, ADDR_B: {"leverage": 6}}},
    )
    r = client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: None}},
    )
    assert r.status_code == 200
    overrides = r.json()["leader_overrides"]
    assert ADDR_A not in overrides
    assert ADDR_B in overrides  # untouched


def test_patch_without_leader_overrides_key_leaves_existing_overrides(
    client: TestClient, auth_headers: dict
) -> None:
    client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 5}}},
    )
    r = client.patch("/api/settings", headers=auth_headers, json={"dry_run": False})
    assert r.status_code == 200
    assert ADDR_A in r.json()["leader_overrides"]


def test_patch_invalid_value_422_and_file_untouched(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    # establish a known-good baseline on disk first
    r = client.patch("/api/settings", headers=auth_headers, json={"dry_run": False})
    assert r.status_code == 200
    settings_path = config.data_dir / "settings.json"
    before = settings_path.read_text()

    r = client.patch("/api/settings", headers=auth_headers, json={"leverage": 999})
    assert r.status_code == 422
    assert "detail" in r.json()

    after = settings_path.read_text()
    assert after == before


def test_patch_unknown_field_is_422(client: TestClient, auth_headers: dict) -> None:
    r = client.patch("/api/settings", headers=auth_headers, json={"not_a_real_field": 1})
    assert r.status_code == 422


def test_patch_bad_leader_override_value_422_and_file_untouched(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    settings_path = config.data_dir / "settings.json"
    assert not settings_path.exists()
    r = client.patch(
        "/api/settings",
        headers=auth_headers,
        json={"leader_overrides": {ADDR_A: {"leverage": 999}}},
    )
    assert r.status_code == 422
    assert not settings_path.exists()


# ── audit H4: contract_version is server-set ───────────────────────────────

def test_old_contract_version_in_file_reads_back_as_the_running_one(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    from contracts.models import CONTRACT_VERSION
    config.data_dir.mkdir(parents=True, exist_ok=True)
    path = config.data_dir / "settings.json"
    path.write_text(json.dumps({"contract_version": 2, "enabled": False, "dry_run": True,
                                "leaders": []}))
    r = client.get("/api/settings", headers=auth_headers)
    assert r.json()["contract_version"] == CONTRACT_VERSION
    assert client.get("/api/health").json()["contract_version"] == CONTRACT_VERSION
    # a client cannot write an old one back either, and any write migrates the file
    r = client.patch("/api/settings", headers=auth_headers, json={"contract_version": 2})
    assert r.status_code == 200 and r.json()["contract_version"] == CONTRACT_VERSION
    assert json.loads(path.read_text())["contract_version"] == CONTRACT_VERSION


def test_follow_their_leverage_on_a_v2_file_stores_leverage_mode_match(
    client: TestClient, auth_headers: dict, config: Config
) -> None:
    """S1: the ticket's "Follow their leverage" must reach the book as leverage_mode
    match, never fall back to the global (default max)."""
    from contracts.models import CONTRACT_VERSION
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / "settings.json").write_text(json.dumps({"contract_version": 2}))
    r = client.post(f"/api/wallets/{ADDR_A}/copy", headers=auth_headers,
                    json={"settings_source": "custom", "allocation_usd": 100.0,
                          "exposure_mode": "match", "leverage_mode": "match"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["contract_version"] == CONTRACT_VERSION
    assert s["leader_overrides"][ADDR_A]["leverage_mode"] == "match"
    eff = client.get("/api/settings", headers=auth_headers).json()
    assert eff["leader_overrides"][ADDR_A]["leverage_mode"] == "match"
