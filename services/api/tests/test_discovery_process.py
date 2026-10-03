"""Discovery runs execute in a child process (api.discovery_client). These
test the child's entry point in-process against a fake discovery.public, and
the parent's message handling, without spawning or touching HL."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from contracts.models import DiscoveryRun, Settings

from api import discovery_client as dc


class FakeConn:
    def __init__(self) -> None:
        self.sent = []

    def send(self, msg) -> None:
        self.sent.append(msg)


def _fake_public(monkeypatch, start, statuses):
    mod = types.ModuleType("discovery.public")
    mod.start_run = start
    seq = iter(statuses)

    def get_run(run_id):
        return DiscoveryRun(run_id=run_id, started_ms=0, status=next(seq), sim_equity_usd=1.0,
                            sim_settings=Settings(), candidates=0, scored=0)
    mod.get_run = get_run
    pkg = types.ModuleType("discovery")
    pkg.public = mod
    monkeypatch.setitem(sys.modules, "discovery", pkg)
    monkeypatch.setitem(sys.modules, "discovery.public", mod)


def test_child_runs_at_background_priority_without_the_key_and_waits_for_the_run(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}
    monkeypatch.setenv("COPYCAT_AGENT_KEY", "0xsecret")
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "engine")

    def start(settings, eq, top):
        seen["priority"] = os.environ.get("COPYCAT_HL_PRIORITY")
        seen["key"] = os.environ.get("COPYCAT_AGENT_KEY")
        seen["data_dir"] = os.environ.get("COPYCAT_DATA_DIR")
        return "run-1"
    _fake_public(monkeypatch, start, ["running", "running", "done"])
    conn = FakeConn()
    dc.run_child(conn, Settings().model_dump_json(), 100.0, 5, str(tmp_path), poll_s=0)
    assert conn.sent == [("ok", "run-1")]
    assert seen == {"priority": "background", "key": None, "data_dir": str(tmp_path)}


def test_child_reports_busy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def start(*a):
        raise RuntimeError("a discovery run is already in progress")
    _fake_public(monkeypatch, start, [])
    conn = FakeConn()
    dc.run_child(conn, Settings().model_dump_json(), 100.0, 5, str(tmp_path), poll_s=0)
    assert conn.sent[0][0] == "busy"


@pytest.mark.parametrize("msg,exc", [(("busy", "x"), dc.DiscoveryBusy),
                                     (("unavailable", "x"), dc.DiscoveryUnavailable),
                                     (("error", "x"), dc.DiscoveryUnavailable)])
def test_parent_maps_child_messages(monkeypatch, msg, exc) -> None:
    client = dc.RealDiscoveryClient(Path("/tmp"))
    monkeypatch.setattr(client, "_spawn", lambda *a: msg)
    with pytest.raises(exc):
        client.start_run(Settings(), 1.0, 1)


def test_parent_returns_the_run_id(monkeypatch) -> None:
    client = dc.RealDiscoveryClient(Path("/tmp"))
    monkeypatch.setattr(client, "_spawn", lambda *a: ("ok", "run-9"))
    assert client.start_run(Settings(), 1.0, 1) == "run-9"
