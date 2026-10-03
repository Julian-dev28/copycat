"""api.thesis_client's child entry point run in-process against a stand-in
discovery.thesis.public (no spawn, no HL), the parent's message handling,
and api.market_client's lazy lookup."""
from __future__ import annotations

import os
import sys
import types

import pytest

from contracts.models import Thesis
from api import thesis_client as tc
from api.market_client import MarketUnavailable, RealMarketClient

from api_fakes import ADDR_A, make_fingerprint


class FakeConn:
    def __init__(self) -> None:
        self.sent = []

    def send(self, msg) -> None:
        self.sent.append(msg)


def _install(monkeypatch, **fns) -> types.ModuleType:
    mod = types.ModuleType("discovery.thesis.public")
    for k, v in fns.items():
        setattr(mod, k, v)
    pkg = types.ModuleType("discovery.thesis")
    pkg.public = mod
    monkeypatch.setitem(sys.modules, "discovery.thesis", pkg)
    monkeypatch.setitem(sys.modules, "discovery.thesis.public", mod)
    return mod


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("COPYCAT_AGENT_KEY", "secret")
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "engine")
    monkeypatch.setenv("COPYCAT_DATA_DIR", "/elsewhere")


def test_child_ok_saves_ta_thesis_and_drops_key(monkeypatch) -> None:
    saved = []
    ta = Thesis(address=ADDR_A, source="ta", created_ms=1, title="t", markdown="m")
    _install(monkeypatch, fingerprint=lambda a, window_days: make_fingerprint(a, window_days),
             ta_thesis=lambda a: ta, save_thesis=saved.append)
    conn = FakeConn()
    tc.fingerprint_child(conn, ADDR_A, 14, "/data/abs")
    kind, value = conn.sent[0]
    assert kind == "ok" and value["window_days"] == 14
    assert saved == [ta]
    assert "COPYCAT_AGENT_KEY" not in os.environ
    assert os.environ["COPYCAT_HL_PRIORITY"] == "background"
    assert os.environ["COPYCAT_DATA_DIR"] == "/data/abs"


def test_child_ta_failure_keeps_fingerprint(monkeypatch) -> None:
    def boom(a):
        raise RuntimeError("no candles")
    _install(monkeypatch, fingerprint=lambda a, window_days: make_fingerprint(a), ta_thesis=boom,
             save_thesis=lambda t: None)
    conn = FakeConn()
    tc.fingerprint_child(conn, ADDR_A, 30, "/d")
    assert conn.sent[0][0] == "ok"


def test_child_errors(monkeypatch) -> None:
    def boom(a, window_days):
        raise ValueError("bad fills")
    _install(monkeypatch, fingerprint=boom)
    conn = FakeConn()
    tc.fingerprint_child(conn, ADDR_A, 30, "/d")
    assert conn.sent == [("error", "ValueError: bad fills")]
    monkeypatch.setitem(sys.modules, "discovery.thesis", None)
    conn = FakeConn()
    tc.fingerprint_child(conn, ADDR_A, 30, "/d")
    assert conn.sent[0][0] == "unavailable"


@pytest.mark.parametrize("msg,exc", [(("unavailable", "x"), tc.ThesisUnavailable),
                                     (("error", "x"), tc.FingerprintFailed)])
def test_parent_maps_child_messages(monkeypatch, tmp_path, msg, exc) -> None:
    c = tc.RealThesisClient(tmp_path)
    monkeypatch.setattr(c, "_spawn", lambda a, w: msg)
    with pytest.raises(exc):
        c.fingerprint(ADDR_A, 30)
    monkeypatch.setattr(c, "_spawn", lambda a, w: ("ok", make_fingerprint(a).model_dump(mode="json")))
    assert c.fingerprint(ADDR_A, 30).address == ADDR_A


def test_theses_and_save_lazy(monkeypatch, tmp_path) -> None:
    store = []
    _install(monkeypatch, get_theses=lambda a: [t.model_dump() for t in store], save_thesis=store.append)
    c = tc.RealThesisClient(tmp_path)
    t = Thesis(address=ADDR_A, source="claude_code", created_ms=1, title="t", markdown="m")
    c.save(t)
    assert c.theses(ADDR_A) == [t]
    monkeypatch.setitem(sys.modules, "discovery.thesis", None)
    with pytest.raises(tc.ThesisUnavailable):
        c.theses(ADDR_A)


def test_market_client_lazy(monkeypatch) -> None:
    mod = types.ModuleType("discovery.public")
    pkg = types.ModuleType("discovery")
    pkg.public = mod
    monkeypatch.setitem(sys.modules, "discovery", pkg)
    monkeypatch.setitem(sys.modules, "discovery.public", mod)
    with pytest.raises(MarketUnavailable):
        RealMarketClient().candles("BTC", "1h", 0, 1)
    mod.candles = lambda coin, iv, s, e: [{"t_ms": s, "o": 1, "h": 1, "l": 1, "c": 1, "v": 0}]
    assert RealMarketClient().candles("BTC", "1h", 5, 9)[0].t_ms == 5
    assert os.environ["COPYCAT_HL_PRIORITY"] == "background"
