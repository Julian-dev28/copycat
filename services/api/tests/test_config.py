from __future__ import annotations

from pathlib import Path

import pytest

from api.config import Config


def test_refuses_to_start_without_token_on_non_localhost_bind() -> None:
    cfg = Config(api_token=None, bind="0.0.0.0")
    with pytest.raises(RuntimeError, match="COPYCAT_API_TOKEN"):
        cfg.validate_or_raise()


def test_allows_missing_token_on_localhost_bind() -> None:
    cfg = Config(api_token=None, bind="127.0.0.1")
    cfg.validate_or_raise()  # must not raise


def test_allows_token_on_any_bind() -> None:
    cfg = Config(api_token="x", bind="0.0.0.0")
    cfg.validate_or_raise()  # must not raise


def test_create_app_refuses_to_start_without_token(data_dir: Path) -> None:
    from api.main import create_app

    cfg = Config(data_dir=data_dir, api_token=None, bind="0.0.0.0")
    with pytest.raises(RuntimeError, match="COPYCAT_API_TOKEN"):
        create_app(cfg)


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "COPYCAT_DATA_DIR",
        "COPYCAT_API_TOKEN",
        "COPYCAT_BIND",
        "COPYCAT_API_PORT",
        "COPYCAT_WEB_ORIGIN",
        "COPYCAT_SSE_POLL_S",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.bind == "127.0.0.1"
    assert cfg.api_token is None
    assert cfg.api_port == 8787
    assert cfg.web_origin == "http://localhost:3000"
    assert str(cfg.data_dir) == "data" or str(cfg.data_dir) == "./data"


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_API_TOKEN", "secret")
    monkeypatch.setenv("COPYCAT_BIND", "0.0.0.0")
    monkeypatch.setenv("COPYCAT_API_PORT", "9999")
    monkeypatch.setenv("COPYCAT_WEB_ORIGIN", "http://example.com")
    cfg = Config.from_env()
    assert cfg.data_dir == tmp_path
    assert cfg.api_token == "secret"
    assert cfg.bind == "0.0.0.0"
    assert cfg.api_port == 9999
    assert cfg.web_origin == "http://example.com"
