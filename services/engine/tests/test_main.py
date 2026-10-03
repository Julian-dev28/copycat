"""`python -m engine` entrypoint guards. Never starts the loop: every test
here stops at an early exit or a patched run_forever."""
from __future__ import annotations

import pytest

import engine.__main__ as entry


def test_skip_dotenv_never_reads_the_repo_env(monkeypatch, tmp_path):
    import dotenv

    called = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: called.append(1))
    monkeypatch.setenv("COPYCAT_SKIP_DOTENV", "1")
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS", raising=False)
    with pytest.raises(SystemExit):
        entry.main()
    assert called == []


def test_data_dir_is_made_absolute_and_second_worker_exits_1(monkeypatch, tmp_path):
    import types
    import sys

    from engine import public

    monkeypatch.setenv("COPYCAT_SKIP_DOTENV", "1")
    monkeypatch.delenv("COPYCAT_AGENT_KEY", raising=False)
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", "0x" + "0" * 40)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COPYCAT_DATA_DIR", "data")
    monkeypatch.setitem(sys.modules, "hl", types.SimpleNamespace(HlVenue=lambda: object()))

    def busy(venue, max_cycles=None):
        raise public.EngineAlreadyRunning("held")
    monkeypatch.setattr(public, "run_forever", busy)
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert e.value.code == 1
    import os
    assert os.environ["COPYCAT_DATA_DIR"] == str((tmp_path / "data").resolve())
