"""Gate test for the e2e mock Hyperliquid: the REAL services/hl venue (SDK signing
included) talks to it over loopback, and the mock records exactly what was sent.
No network beyond 127.0.0.1."""
from __future__ import annotations

import json
import secrets
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from eth_account import Account

import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("e2e_mock_hl_server", pathlib.Path(__file__).with_name("server.py"))
mock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock)  # type: ignore[union-attr]


@pytest.fixture()
def hl_mock(monkeypatch, tmp_path):
    mock.STATE.reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    for k in ("COPYCAT_AGENT_KEY", "COPYCAT_ACCOUNT_ADDRESS", "COPYCAT_NETWORK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", url)
    monkeypatch.setenv("COPYCAT_E2E", "1")
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path / "data"))
    from hl import meta, sdk
    from hl import venue as venue_mod
    from hl.http import reset_session
    from hl.rate_limit import TokenBucket
    # never the shared file bucket: rate_limit resolves ./data at import time,
    # which could be the operator's live data dir
    monkeypatch.setattr("hl.rate_limit.HL_LIMITER", TokenBucket(capacity=1_000_000, refill_per_sec=1_000_000))
    venue_mod._abstraction.clear()
    venue_mod._active_dexes.clear()
    meta.reset_caches()
    sdk.reset()
    reset_session()
    yield url
    srv.shutdown()
    sdk.reset()
    meta.reset_caches()


def _ctl(url, path, body=None):
    req = urllib.request.Request(url + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _account(url, monkeypatch):
    main = Account.create(extra_entropy=secrets.token_hex(16))
    agent = Account.create(extra_entropy=secrets.token_hex(16))
    _ctl(url, "/__mock/user", {"address": main.address, "cash": 1000, "agents": [{"address": agent.address}]})
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", main.address)
    monkeypatch.setenv("COPYCAT_AGENT_KEY", agent.key.hex())
    return main, agent


def test_reads_parse_through_the_real_venue(hl_mock):
    from hl import HlVenue
    v = HlVenue()
    st = v.account_state("0x1111111111111111111111111111111111111111")
    assert st is not None and st["equity_perp_usd"] == 250000.0 and st["positions"] == {}
    assert v.mid("BTC") == 100000.0
    assert v.max_leverage("BTC") == 40
    assert v.is_isolated_only("HYPE") is True
    assert v.depth_usd("BTC", True, 1.0) > 1000
    assert len(v.leaderboard()) == 3


def test_order_is_signature_checked_filled_and_recorded(hl_mock, monkeypatch):
    from hl import HlVenue
    main, agent = _account(hl_mock, monkeypatch)
    v = HlVenue()
    assert v.set_leverage("BTC", 5, False) == {"ok": True}
    res = v.market("BTC", True, 0.0025, 100000.0)
    assert res["ok"] is True and res["filled_sz"] == 0.0025
    rec = _ctl(hl_mock, "/__mock/exchange")
    assert [r["type"] for r in rec] == ["updateLeverage", "order"]
    assert rec[0]["user"] == main.address.lower() and rec[0]["signer"] == agent.address.lower()
    assert rec[0]["leverage"] == 5 and rec[0]["is_cross"] is False
    o = rec[1]["orders"][0]
    assert (o["coin"], o["side"], o["sz"], o["tif"], o["reduce_only"], o["leverage"], o["is_cross"]) == \
        ("BTC", "buy", 0.0025, "Ioc", False, 5, False)
    st = v.account_state(main.address)
    assert st["positions"]["BTC"]["szi"] == 0.0025 and st["positions"]["BTC"]["is_cross"] is False
    assert st["positions"]["BTC"]["lev"] == 5
    # close: reduce-only, sized off our own live position, confirmed flat
    assert v.close("BTC")["ok"] is True
    last = _ctl(hl_mock, "/__mock/exchange?since=2")
    assert last[0]["orders"][0]["reduce_only"] is True and last[0]["orders"][0]["side"] == "sell"
    assert v.account_state(main.address)["positions"] == {}


def test_unapproved_agent_is_rejected_like_hl(hl_mock, monkeypatch):
    from hl import HlVenue
    main = Account.create()
    stranger = Account.create()
    _ctl(hl_mock, "/__mock/user", {"address": main.address, "cash": 1000})
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", main.address)
    monkeypatch.setenv("COPYCAT_AGENT_KEY", stranger.key.hex())
    res = HlVenue().market("BTC", True, 0.001, 100000.0)
    assert res["ok"] is False and "does not exist" in res["error"]
    assert _ctl(hl_mock, "/__mock/state")["users"][main.address.lower()]["positions"] == {}


def test_ioc_below_mid_does_not_fill(hl_mock, monkeypatch):
    main, _ = _account(hl_mock, monkeypatch)
    from hl import HlVenue
    _ctl(hl_mock, "/__mock/mids", {"ETH": 4000})
    v = HlVenue()
    # the venue caps a buy at mid*(1+slip); a stale mid far below the live one cannot cross
    res = v.market("ETH", True, 0.01, 3000.0, max_slippage_pct=1.0)
    assert res["ok"] is False


def test_leader_position_control(hl_mock):
    from hl import HlVenue
    lead = "0x2222222222222222222222222222222222222222"
    _ctl(hl_mock, "/__mock/user", {"address": lead, "positions": {"ETH": {"szi": -3, "leverage": 10}}})
    st = HlVenue().account_state(lead)
    assert st["positions"]["ETH"]["szi"] == -3 and st["positions"]["ETH"]["lev"] == 10
    _ctl(hl_mock, "/__mock/user", {"address": lead, "positions": {"ETH": {"szi": 0}}})
    assert HlVenue().account_state(lead)["positions"] == {}
