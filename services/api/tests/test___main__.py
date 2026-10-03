from __future__ import annotations

from pathlib import Path

import pytest

import api.__main__ as entrypoint


def test_main_runs_uvicorn_with_env_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {}

    def fake_run(app, host, port, **kwargs):
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(entrypoint.uvicorn, "run", fake_run)
    monkeypatch.setenv("COPYCAT_SKIP_DOTENV", "1")   # never read the repo's real .env
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_API_TOKEN", "t" * 32)
    monkeypatch.setenv("COPYCAT_BIND", "0.0.0.0")
    monkeypatch.setenv("COPYCAT_API_PORT", "9999")

    entrypoint.main()

    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 9999
    assert calls["app"] is not None


def test_skip_dotenv_never_calls_load_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import dotenv

    called = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: called.append(1))
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setenv("COPYCAT_SKIP_DOTENV", "1")
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_API_TOKEN", "t" * 32)
    entrypoint.main()
    assert called == []
