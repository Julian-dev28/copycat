"""settings_io.load_settings: reload-every-cycle semantics, fallback to the
last known-good settings (persisted in SQLite) on a missing/invalid file."""
from __future__ import annotations

import json

from engine import settings_io
from engine.state import EngineState


def test_missing_file_on_first_boot_is_safe_defaults_not_an_error(tmp_path):
    with EngineState(tmp_path / "e.db") as state:
        settings, error = settings_io.load_settings(tmp_path / "settings.json", state)
        assert error is None
        assert settings.enabled is False
        assert settings.dry_run is True


def test_valid_file_parses_and_becomes_the_new_last_good(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabled": True, "dry_run": False, "leaders": ["0x" + "a" * 40]}))
    with EngineState(tmp_path / "e.db") as state:
        settings, error = settings_io.load_settings(path, state)
        assert error is None
        assert settings.enabled is True
        assert settings.dry_run is False
        assert settings.leaders == ["0x" + "a" * 40]
        assert state.get_kv("last_good_settings")["enabled"] is True


def test_invalid_json_falls_back_to_last_good_with_an_error(tmp_path):
    path = tmp_path / "settings.json"
    with EngineState(tmp_path / "e.db") as state:
        path.write_text(json.dumps({"enabled": True, "poll_interval_s": 9}))
        good, err0 = settings_io.load_settings(path, state)
        assert err0 is None and good.enabled is True

        path.write_text("{not valid json")
        settings, error = settings_io.load_settings(path, state)
        assert error is not None
        assert "invalid" in error
        assert settings.enabled is True            # kept the last good settings
        assert settings.poll_interval_s == 9


def test_invalid_json_with_no_prior_good_copy_uses_safe_defaults_and_errors(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not valid json")
    with EngineState(tmp_path / "e.db") as state:
        settings, error = settings_io.load_settings(path, state)
        assert error is not None
        assert settings.enabled is False
        assert settings.dry_run is True


def test_validation_error_falls_back_to_last_good_with_an_error(tmp_path):
    path = tmp_path / "settings.json"
    with EngineState(tmp_path / "e.db") as state:
        path.write_text(json.dumps({"enabled": True}))
        good, _ = settings_io.load_settings(path, state)
        assert good.enabled is True

        path.write_text(json.dumps({"leverage": 999}))  # fails the ge/le=50 constraint
        settings, error = settings_io.load_settings(path, state)
        assert error is not None
        assert settings.enabled is True


def test_file_disappearing_after_a_good_read_keeps_last_good_with_an_error(tmp_path):
    path = tmp_path / "settings.json"
    with EngineState(tmp_path / "e.db") as state:
        path.write_text(json.dumps({"enabled": True, "sleeve_frac": 0.3}))
        good, _ = settings_io.load_settings(path, state)
        assert good.enabled is True

        path.unlink()
        settings, error = settings_io.load_settings(path, state)
        assert error is not None
        assert "missing" in error
        assert settings.enabled is True
        assert settings.sleeve_frac == 0.3


def test_last_good_survives_a_fresh_engine_state_instance_restart(tmp_path):
    path = tmp_path / "settings.json"
    db_path = tmp_path / "e.db"
    path.write_text(json.dumps({"enabled": True, "dry_run": False}))
    with EngineState(db_path) as state:
        settings_io.load_settings(path, state)

    path.write_text("{broken")
    with EngineState(db_path) as state2:   # simulates an engine restart: new connection, same file
        settings, error = settings_io.load_settings(path, state2)
        assert error is not None
        assert settings.enabled is True
        assert settings.dry_run is False
