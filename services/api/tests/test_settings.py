from __future__ import annotations

import json
from pathlib import Path

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
