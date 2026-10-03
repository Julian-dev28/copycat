from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from api.config import Config, resolve_api_token

GOOD = "a" * 32


def test_short_env_token_is_refused() -> None:
    with pytest.raises(RuntimeError, match="32-char minimum"):
        Config(data_dir=Path("/nonexistent"), api_token="x" * 31).validate_or_raise()


@pytest.mark.parametrize("placeholder", ["change-me", "CHANGE-ME", "changeme"])
def test_placeholder_token_is_refused(placeholder: str, data_dir: Path) -> None:
    with pytest.raises(RuntimeError, match="placeholder"):
        Config(data_dir=data_dir, api_token=placeholder).validate_or_raise()


def test_good_env_token_is_used_on_any_bind(data_dir: Path) -> None:
    cfg = Config(data_dir=data_dir, api_token=GOOD, bind="0.0.0.0")
    cfg.validate_or_raise()
    assert cfg.api_token == GOOD and cfg.token_source == "COPYCAT_API_TOKEN"
    assert not (data_dir / "api_token").exists()


def test_empty_token_on_0000_generates_0600_file_and_reuses_it_on_restart(
        data_dir: Path, capsys: pytest.CaptureFixture) -> None:
    # docker-compose: COPYCAT_API_TOKEN="" with COPYCAT_BIND=0.0.0.0 must start, not refuse
    first = Config(data_dir=data_dir, api_token=None, bind="0.0.0.0")
    first.validate_or_raise()
    path = data_dir / "api_token"
    assert path.exists() and len(first.api_token) >= 32
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    err = capsys.readouterr().err
    assert str(path) in err and first.api_token not in err          # path printed, never the token

    second = Config(data_dir=data_dir, api_token=None, bind="0.0.0.0")   # restart
    second.validate_or_raise()
    assert second.api_token == first.api_token
    assert capsys.readouterr().err == ""


def test_a_tampered_short_token_file_is_refused(data_dir: Path) -> None:
    (data_dir / "api_token").write_text("short\n")
    with pytest.raises(RuntimeError, match="api_token"):
        resolve_api_token(data_dir, None)


def test_create_app_drops_the_agent_key_from_the_api_process(
        data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import create_app

    monkeypatch.setenv("COPYCAT_AGENT_KEY", "0x" + "ab" * 32)
    create_app(Config(data_dir=data_dir, api_token=GOOD))
    assert "COPYCAT_AGENT_KEY" not in os.environ


def test_importing_api_main_builds_no_app_and_writes_nothing(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COPYCAT_DATA_DIR", raising=False)
    import api.main
    importlib.reload(api.main)
    assert not (tmp_path / "data").exists()


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("COPYCAT_DATA_DIR", "COPYCAT_API_TOKEN", "COPYCAT_BIND", "COPYCAT_API_PORT",
                "COPYCAT_WEB_ORIGIN", "COPYCAT_SSE_POLL_S", "COPYCAT_ALLOWED_HOSTS",
                "COPYCAT_ACCOUNT_ADDRESS"):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.bind == "127.0.0.1"
    assert cfg.api_token is None
    assert cfg.api_port == 8787
    assert cfg.web_origin == "http://localhost:3000"
    assert cfg.data_dir == (Path.cwd() / "data").resolve() and cfg.data_dir.is_absolute()
    assert os.environ["COPYCAT_DATA_DIR"] == str(cfg.data_dir)
    assert cfg.allowed_hosts == ["localhost", "127.0.0.1"]
    assert cfg.our_address is None


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_API_TOKEN", "secret")
    monkeypatch.setenv("COPYCAT_BIND", "0.0.0.0")
    monkeypatch.setenv("COPYCAT_API_PORT", "9999")
    monkeypatch.setenv("COPYCAT_WEB_ORIGIN", "http://example.com")
    monkeypatch.setenv("COPYCAT_ALLOWED_HOSTS", "copycat.lan, 10.0.0.5")
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", "0xABC")
    cfg = Config.from_env()
    assert cfg.data_dir == tmp_path
    assert cfg.api_token == "secret"
    assert cfg.bind == "0.0.0.0"
    assert cfg.api_port == 9999
    assert cfg.web_origin == "http://example.com"
    assert cfg.allowed_hosts == ["localhost", "127.0.0.1", "copycat.lan", "10.0.0.5"]
    assert cfg.our_address == "0xabc"
