"""Gate tests for hl.venue.HlVenue: fake _http_post / fake SDK, no network,
<2s. Covers every read/write contract rule from contracts/venue.py:
account_state multi-dex aggregation, extras pricing-by-index + illiquid
exclusion, fills pagination, leaderboard/candles parsing, set_leverage
strict + isolated-only fallback, and the no-key write refusal.
market/close/order_status (contract v2) live in test_venue_writes.py.
"""
from __future__ import annotations

from hl import meta, sdk
from hl import venue as venue_mod
from hl.venue import HlVenue


def _chs(account_value=100.0, withdrawable=50.0, positions=None):
    """A clearinghouseState-shaped response."""
    return {
        "marginSummary": {"accountValue": str(account_value)},
        "withdrawable": str(withdrawable),
        "assetPositions": positions or [],
    }


def _pos(coin, szi, entry_px=100.0, lev_value=10, lev_type="cross"):
    return {"position": {
        "coin": coin, "szi": str(szi), "entryPx": str(entry_px),
        "leverage": {"type": lev_type, "value": lev_value},
    }}


# ── account_state ────────────────────────────────────────────────────────────

def test_account_state_aggregates_main_plus_hip3_dexes(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])

    def fake_post(path, payload, **kw):
        dex = payload.get("dex")
        t = payload["type"]
        if t == "clearinghouseState" and dex == "":
            return _chs(account_value=100.0, withdrawable=40.0, positions=[_pos("BTC", 1.5)])
        if t == "clearinghouseState" and dex == "xyz":
            return _chs(account_value=20.0, withdrawable=5.0, positions=[_pos("TSLA", -2.0, lev_type="isolated")])
        if t == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": "7.5"}]}
        raise AssertionError(f"unexpected call {payload}")

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    state = HlVenue().account_state("0xabc")
    assert state is not None
    assert state["equity_perp_usd"] == 120.0
    assert state["spot_usdc"] == 7.5
    assert state["available"] == {"": 40.0, "xyz": 5.0}
    assert state["positions"]["BTC"] == {"szi": 1.5, "entry_px": 100.0, "lev": 10.0, "is_cross": True}
    # HIP-3 dex position is namespaced dex:coin
    assert "xyz:TSLA" in state["positions"]
    assert state["positions"]["xyz:TSLA"]["is_cross"] is False
    assert state["raw_positions"]["xyz:TSLA"]["coin"] == "TSLA"  # raw, unprefixed


def test_account_state_hip3_coin_already_namespaced_not_double_prefixed(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["xyz"])

    def fake_post(path, payload, **kw):
        if payload["type"] == "clearinghouseState":
            return _chs(positions=[_pos("xyz:TSLA", 1.0)])
        return {"balances": []}

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    state = HlVenue().account_state("0xabc")
    assert "xyz:TSLA" in state["positions"]
    assert "xyz:xyz:TSLA" not in state["positions"]


def test_account_state_zero_size_position_excluded(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: [""])

    def fake_post(path, payload, **kw):
        if payload["type"] == "clearinghouseState":
            return _chs(positions=[_pos("BTC", 0)])
        return {"balances": []}

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    state = HlVenue().account_state("0xabc")
    assert state["positions"] == {}


def test_account_state_none_when_any_dex_read_fails(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])

    def fake_post(path, payload, **kw):
        if payload.get("dex") == "xyz":
            return None  # failed read for the second dex
        return _chs()

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    assert HlVenue().account_state("0xabc") is None


def test_account_state_none_when_spot_read_fails(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: [""])

    def fake_post(path, payload, **kw):
        if payload["type"] == "clearinghouseState":
            return _chs()
        return None

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    assert HlVenue().account_state("0xabc") is None


# ── extras: pricing by index + illiquid-mark exclusion ──────────────────────

def test_extras_prices_spot_other_and_staked_hype(monkeypatch):
    def fake_post(path, payload, **kw):
        t = payload["type"]
        if t == "spotClearinghouseState":
            return {"balances": [
                {"coin": "USDC", "total": "10"},
                {"coin": "FOO", "total": "100"},
            ]}
        if t == "delegatorSummary":
            return {"delegated": "5", "undelegated": "1", "totalPendingWithdrawal": "0"}
        raise AssertionError(payload)

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    monkeypatch.setattr(meta, "spot_prices", lambda: {"FOO": (2.0, 1_000_000.0), "HYPE": (10.0, 1_000_000.0)})
    extras = HlVenue().extras("0xabc")
    assert extras == {"spot_other_usd": 200.0, "staked_hype_usd": 60.0}  # (5+1)*10


def test_extras_illiquid_mark_counts_as_zero_the_1b_max_scenario(monkeypatch):
    """The real incident this guards against: a leader's spot balance in a
    thinly-traded token priced out to roughly $1B ('MAX'), while that
    token's whole 24h pair volume was a few thousand dollars. 10x the 24h
    volume is the line; over it, the mark counts as 0 instead of
    inflating the leader's sized equity by a billion dollars."""
    def fake_post(path, payload, **kw):
        t = payload["type"]
        if t == "spotClearinghouseState":
            return {"balances": [
                {"coin": "USDC", "total": "0"},
                {"coin": "ILLIQUID", "total": "1000000000"},  # the "MAX" balance
            ]}
        if t == "delegatorSummary":
            return {"delegated": "0", "undelegated": "0", "totalPendingWithdrawal": "0"}
        raise AssertionError(payload)

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    # price $1.00, so marked value = $1e9; 24h pair volume only $5,000
    monkeypatch.setattr(meta, "spot_prices", lambda: {"ILLIQUID": (1.0, 5_000.0), "HYPE": (10.0, 1.0)})
    extras = HlVenue().extras("0xabc")
    assert extras["spot_other_usd"] == 0.0  # excluded, not $1e9


def test_extras_liquid_mark_under_10x_volume_is_counted(monkeypatch):
    def fake_post(path, payload, **kw):
        t = payload["type"]
        if t == "spotClearinghouseState":
            return {"balances": [{"coin": "OK", "total": "100"}]}
        if t == "delegatorSummary":
            return {"delegated": "0", "undelegated": "0", "totalPendingWithdrawal": "0"}
        raise AssertionError(payload)

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    # value = 100*2 = 200; 10x of 500000 vlm is way above 200 -> counted
    monkeypatch.setattr(meta, "spot_prices", lambda: {"OK": (2.0, 500_000.0), "HYPE": (10.0, 1.0)})
    extras = HlVenue().extras("0xabc")
    assert extras["spot_other_usd"] == 200.0


def test_extras_none_when_spot_read_fails(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: None)
    assert HlVenue().extras("0xabc") is None


def test_extras_none_when_price_table_unavailable(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: {"balances": []})
    monkeypatch.setattr(meta, "spot_prices", lambda: None)
    assert HlVenue().extras("0xabc") is None


def test_extras_none_when_hype_price_missing(monkeypatch):
    def fake_post(path, payload, **kw):
        if payload["type"] == "spotClearinghouseState":
            return {"balances": []}
        return {"delegated": "1", "undelegated": "0", "totalPendingWithdrawal": "0"}

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    monkeypatch.setattr(meta, "spot_prices", dict)  # no HYPE entry
    assert HlVenue().extras("0xabc") is None


def test_extras_none_when_delegator_summary_fails(monkeypatch):
    def fake_post(path, payload, **kw):
        if payload["type"] == "spotClearinghouseState":
            return {"balances": []}
        return None

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    monkeypatch.setattr(meta, "spot_prices", lambda: {"HYPE": (10.0, 1.0)})
    assert HlVenue().extras("0xabc") is None


# ── mid ───────────────────────────────────────────────────────────────────────

def test_mid_happy_path(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: {"BTC": "85000.5"})
    assert HlVenue().mid("BTC") == 85000.5


def test_mid_hip3_coin_passes_dex(monkeypatch):
    seen = {}

    def fake_post(path, payload, **kw):
        seen.update(payload)
        return {"xyz:TSLA": "358.5"}

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    assert HlVenue().mid("xyz:TSLA") == 358.5
    assert seen["dex"] == "xyz"


def test_mid_returns_0_on_failure(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: None)
    assert HlVenue().mid("BTC") == 0.0


def test_mid_returns_0_when_coin_missing(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: {})
    assert HlVenue().mid("BTC") == 0.0


# ── max_leverage / is_isolated_only / size_for delegate correctly ───────────

def test_max_leverage_delegates_to_meta(monkeypatch):
    monkeypatch.setattr(meta, "max_leverage", lambda coin: 33)
    assert HlVenue().max_leverage("BTC") == 33


def test_is_isolated_only_delegates_to_meta(monkeypatch):
    monkeypatch.setattr(meta, "is_isolated_only", lambda coin: True)
    assert HlVenue().is_isolated_only("xyz:HOOD") is True


def test_size_for_delegates_to_sizing(monkeypatch):
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 2)
    assert HlVenue().size_for("BTC", 100.0, 50.0) == 2.0


# ── fills: pagination by last time ───────────────────────────────────────────

def _fill(t, coin="BTC", px=100.0, sz=1.0, side="B"):
    return {"time": t, "coin": coin, "px": str(px), "sz": str(sz), "side": side,
            "dir": "Open Long", "startPosition": "0", "closedPnl": "0", "fee": "0.01"}


def test_fills_single_page(monkeypatch):
    page = [_fill(1000), _fill(2000)]
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: page)
    out = HlVenue().fills("0xabc", 0, 3000)
    assert len(out) == 2
    assert out[0]["time_ms"] == 1000
    assert out[0]["coin"] == "BTC"
    assert out[0]["px"] == 100.0


class _HlFillsServer:
    """Fake userFillsByTime that behaves like HL: rows with startTime <= time
    <= endTime, oldest first, cut at 2000 rows even mid-millisecond."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.calls = []

    def __call__(self, path, payload, **kw):
        self.calls.append(dict(payload))
        rows = [f for f in self.corpus if payload["startTime"] <= f["time"] <= payload["endTime"]]
        return rows[:2000]


def _ids(out):
    return [(f["time_ms"], f["px"]) for f in out]


def test_fills_pages_by_last_time_not_offset(monkeypatch):
    corpus = [_fill(t, px=t) for t in range(2500)]
    srv = _HlFillsServer(corpus)
    monkeypatch.setattr(venue_mod, "http_post", srv)
    out = HlVenue().fills("0xabc", 0, 10_000)
    assert [c["startTime"] for c in srv.calls] == [0, 1999]   # next cursor = last row's time, re-read whole
    assert _ids(out) == [(t, float(t)) for t in range(2500)]   # no loss, no duplicate


def test_fills_page_cut_mid_millisecond_loses_nothing(monkeypatch):
    """Measured on 0xf5d81a13 (aggregated, 2026-10-05): page 1 held 39 rows at
    its last ms, a refetch from that ms returned 49. A `last + 1` cursor lost
    the other 10. Here rows 1990..2009 share t=1990: the cap cuts at 2000."""
    corpus = [_fill(min(i, 1990) if i < 2010 else i, px=i) for i in range(2100)]
    srv = _HlFillsServer(corpus)
    monkeypatch.setattr(venue_mod, "http_post", srv)
    out = HlVenue().fills("0xabc", 0, 10_000)
    assert [c["startTime"] for c in srv.calls] == [0, 1990]
    assert sorted(f["px"] for f in out) == [float(i) for i in range(2100)]
    assert len(out) == 2100


def test_fills_full_page_at_one_millisecond_falls_back_to_plus_one(monkeypatch, caplog):
    corpus = [_fill(7, px=i) for i in range(2000)] + [_fill(8, px=9999)]
    srv = _HlFillsServer(corpus)
    monkeypatch.setattr(venue_mod, "http_post", srv)
    out = HlVenue().fills("0xabc", 0, 100)
    assert [c["startTime"] for c in srv.calls] == [0, 8]      # cannot advance by re-reading t=7
    assert len(out) == 2001 and "one millisecond" in caplog.text


def test_fills_aggregate_by_time_flag_reaches_hl(monkeypatch):
    srv = _HlFillsServer([_fill(1)])
    monkeypatch.setattr(venue_mod, "http_post", srv)
    HlVenue().fills("0xabc", 0, 10)
    HlVenue().fills("0xabc", 0, 10, aggregate_by_time=True)
    assert "aggregateByTime" not in srv.calls[0]
    assert srv.calls[1]["aggregateByTime"] is True
    assert {k for k in srv.calls[1]} == {"type", "user", "startTime", "endTime", "aggregateByTime"}


def test_fills_accepts_aggregate_kwarg_like_fills_cache_expects():
    import inspect
    assert "aggregate_by_time" in inspect.signature(HlVenue().fills).parameters


def test_fills_stops_after_max_pages_safety_valve(monkeypatch, caplog):
    calls = {"n": 0}

    def fake_post(path, payload, **kw):
        calls["n"] += 1
        # always return a full page -- never shrinks, pathological API
        return [_fill(payload["startTime"] + t) for t in range(2000)]

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    out = HlVenue().fills("0xabc", 0, 10**15)
    assert calls["n"] == 50  # MAX_PAGES, never an infinite loop
    assert len(out) == 50 * 1999 + 1   # each page re-reads the previous page's last ms; the final one is kept
    assert "MAX_PAGES" in caplog.text


def test_fills_none_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: None)
    assert HlVenue().fills("0xabc", 0, 1000) is None


def test_fills_none_on_second_page_failure(monkeypatch):
    page1 = [_fill(t) for t in range(2000)]
    calls = {"n": 0}

    def fake_post(path, payload, **kw):
        calls["n"] += 1
        return page1 if calls["n"] == 1 else None

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    assert HlVenue().fills("0xabc", 0, 10**15) is None


def test_fills_drops_unparseable_fill_but_keeps_the_rest(monkeypatch):
    bad = {"time": 5, "coin": "BTC"}  # missing px/sz/side
    good = _fill(10)
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: [bad, good])
    out = HlVenue().fills("0xabc", 0, 1000)
    assert len(out) == 1
    assert out[0]["time_ms"] == 10


# ── leaderboard ───────────────────────────────────────────────────────────────

class _FakeLbResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def test_leaderboard_happy_path(monkeypatch):
    rows = [{"ethAddress": "0xabc", "accountValue": "123.0", "windowPerformances": [
        ["day", {"pnl": "1.0", "roi": "0.01", "vlm": "10.0"}],
    ], "prize": 0, "displayName": None}]
    monkeypatch.setattr(
        "hl.venue.requests.get",
        lambda url, timeout=None: _FakeLbResponse({"leaderboardRows": rows}),
    )
    out = HlVenue().leaderboard()
    assert out == rows


def test_leaderboard_hits_mainnet_or_testnet_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "hl.venue.requests.get",
        lambda url, timeout=None: seen.setdefault("url", url) and _FakeLbResponse({"leaderboardRows": []}),
    )
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    HlVenue().leaderboard()
    assert "/Testnet/leaderboard" in seen["url"]


def test_leaderboard_none_on_fetch_failure(monkeypatch):
    def boom(url, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("hl.venue.requests.get", boom)
    assert HlVenue().leaderboard() is None


def test_leaderboard_none_on_bad_shape(monkeypatch):
    monkeypatch.setattr("hl.venue.requests.get", lambda url, timeout=None: _FakeLbResponse({"nope": []}))
    assert HlVenue().leaderboard() is None


# ── candles ──────────────────────────────────────────────────────────────────

def test_candles_happy_path(monkeypatch):
    rows = [{"t": 1, "c": "100"}]
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: rows)
    assert HlVenue().candles("BTC", "1h", 0, 3_600_000) == rows


def test_candles_none_on_failure(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: None)
    assert HlVenue().candles("BTC", "1h", 0, 3_600_000) is None


def test_candles_empty_list_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: [])
    assert HlVenue().candles("BTC", "1h", 0, 3_600_000) == []


# ── writes: no-key refusal ───────────────────────────────────────────────────

def test_set_leverage_refuses_without_keys():
    out = HlVenue().set_leverage("BTC", 10, True)
    assert out == {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}


def test_market_refuses_without_keys():
    out = HlVenue().market("BTC", True, 1.0, 100.0)
    assert out["ok"] is False
    assert "COPYCAT_AGENT_KEY" in out["error"]


def test_close_refuses_without_keys():
    out = HlVenue().close("BTC")
    assert out["ok"] is False
    assert "COPYCAT_AGENT_KEY" in out["error"]


# ── set_leverage: strict + isolated-only fallback ───────────────────────────

class _FakeExchange:
    def __init__(self, leverage_result=None, order_result=None):
        self.leverage_result = leverage_result
        self.order_result = order_result
        self.leverage_calls = []
        self.order_calls = []

    def update_leverage(self, leverage, coin, is_cross=True):
        self.leverage_calls.append((leverage, coin, is_cross))
        return self.leverage_result

    def order(self, coin, is_buy, sz, px, order_type, reduce_only=False, cloid=None):
        self.order_calls.append((coin, is_buy, sz, px, order_type, reduce_only))
        return self.order_result


def test_set_leverage_strict_ok(write_creds, monkeypatch):
    fake = _FakeExchange(leverage_result={"status": "ok"})
    monkeypatch.setattr(sdk, "get_exchange", lambda: fake)
    out = HlVenue().set_leverage("BTC", 20, True)
    assert out == {"ok": True}
    assert fake.leverage_calls == [(20, "BTC", True)]


def test_set_leverage_strict_err_surfaces_hl_error_not_false_success(write_creds, monkeypatch):
    """The known SDK trap: update_leverage can return HTTP 200 with
    {"status": "err", ...} -- strict mode must read the body, not just
    'the call did not raise'."""
    fake = _FakeExchange(leverage_result={"status": "err", "response": "Insufficient margin"})
    monkeypatch.setattr(sdk, "get_exchange", lambda: fake)
    out = HlVenue().set_leverage("BTC", 20, True)
    assert out == {"ok": False, "error": "Insufficient margin"}


def test_set_leverage_isolated_only_market_forces_isolated(write_creds, monkeypatch):
    monkeypatch.setattr(meta, "is_isolated_only", lambda coin: True)
    fake = _FakeExchange(leverage_result={"status": "ok"})
    monkeypatch.setattr(sdk, "get_exchange", lambda: fake)
    HlVenue().set_leverage("xyz:HOOD", 10, True)  # asked for cross
    assert fake.leverage_calls == [(10, "xyz:HOOD", False)]  # applied isolated


def test_set_leverage_rejects_sub_1x(write_creds):
    out = HlVenue().set_leverage("BTC", 0, True)
    assert out["ok"] is False


def test_set_leverage_exception_from_exchange_is_caught(write_creds, monkeypatch):
    class _Boom:
        def update_leverage(self, *a, **k):
            raise RuntimeError("signing blew up")

    monkeypatch.setattr(sdk, "get_exchange", lambda: _Boom())
    out = HlVenue().set_leverage("BTC", 10, True)
    assert out["ok"] is False
    assert "signing blew up" in out["error"]


# ── active-dex cache: fewer reads per cycle, exits never missed ─────────────

def _dex_fake(monkeypatch, holdings):
    """holdings: dex -> (account_value, [coins]). Records every dex read."""
    from hl import meta
    from hl import venue as v
    monkeypatch.delenv("COPYCAT_HL_DEXES", raising=False)
    monkeypatch.setattr(meta, "dex_list", lambda override=None: ["", "xyz", "flx", "km"])
    v._active_dexes.clear()
    v._last_full_scan.clear()
    reads = []

    def fake_post(path, body, **kw):
        if body["type"] == "spotClearinghouseState":
            return {"balances": []}
        dex = body["dex"]
        reads.append(dex)
        av, coins = holdings.get(dex, (0.0, []))
        return {"marginSummary": {"accountValue": str(av)}, "withdrawable": "0",
                "assetPositions": [{"position": {"coin": c, "szi": "1", "entryPx": "1",
                                                 "leverage": {"type": "isolated", "value": 3}}}
                                   for c in coins]}
    monkeypatch.setattr(v, "http_post", fake_post)
    return v, reads


def test_first_read_scans_every_dex_then_only_active_ones(monkeypatch):
    v, reads = _dex_fake(monkeypatch, {"": (100.0, ["BTC"]), "xyz": (5.0, ["TSLA"])})
    venue = v.HlVenue()
    assert venue.account_state("0xabc") is not None
    assert reads == ["", "xyz", "flx", "km"]
    reads.clear()
    st = venue.account_state("0xabc")
    assert reads == ["", "xyz"]
    assert set(st["positions"]) == {"BTC", "xyz:TSLA"}


def test_a_dex_with_a_position_is_always_reread_so_exits_are_seen(monkeypatch):
    holdings = {"": (0.0, []), "km": (0.0, ["GOLD"])}     # km position, zero account value
    v, reads = _dex_fake(monkeypatch, holdings)
    venue = v.HlVenue()
    venue.account_state("0xabc")
    reads.clear()
    holdings["km"] = (0.0, [])                            # he closed it
    st = venue.account_state("0xabc")
    assert "km" in reads and st["positions"] == {}


def test_full_rescan_after_the_interval_finds_a_new_dex(monkeypatch):
    holdings = {"": (10.0, [])}
    v, reads = _dex_fake(monkeypatch, holdings)
    venue = v.HlVenue()
    venue.account_state("0xabc")
    holdings["flx"] = (50.0, ["OIL"])                     # opens on a dex he never used
    reads.clear()
    assert "flx:OIL" not in venue.account_state("0xabc")["positions"]
    v._last_full_scan["0xabc"] -= v.ACTIVE_DEX_RESCAN_S + 1
    assert "flx:OIL" in venue.account_state("0xabc")["positions"]


def test_pinned_dexes_env_reads_exactly_that_set_every_time(monkeypatch):
    v, reads = _dex_fake(monkeypatch, {"": (1.0, [])})
    from hl import meta
    monkeypatch.setenv("COPYCAT_HL_DEXES", ",xyz")
    monkeypatch.setattr(meta, "dex_list", lambda override=None: ["", "xyz"])
    venue = v.HlVenue()
    venue.account_state("0xabc"); venue.account_state("0xabc")
    assert reads == ["", "xyz", "", "xyz"]


# ── account abstraction: unified / portfolio margin ─────────────────────────

def _abstraction_fake(monkeypatch, abstraction, calls=None):
    """Main dex with a misleading $5.7k withdrawable plus xyz; spot USDC
    total 900k with 56k on hold. `abstraction` is what userAbstraction
    returns (a bare JSON string, as curled from mainnet), or None = failed."""
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])

    def fake_post(path, payload, **kw):
        t = payload["type"]
        if calls is not None:
            calls.append(t)
        if t == "clearinghouseState":
            return _chs(account_value=10_000.0, withdrawable=5_700.0 if payload["dex"] == "" else 0.0)
        if t == "spotClearinghouseState":
            return {"balances": [
                {"coin": "USDC", "token": 0, "total": "900000.0", "hold": "56000.0", "entryNtl": "0.0"},
                {"coin": "HYPE", "token": 150, "total": "1.0", "hold": "0.0", "entryNtl": "10.0"},
            ]}
        if t == "userAbstraction":
            assert payload == {"type": "userAbstraction", "user": "0xabc"}
            return abstraction
        raise AssertionError(payload)

    monkeypatch.setattr(venue_mod, "http_post", fake_post)


def test_unified_account_available_is_spot_usdc_free_on_every_dex(monkeypatch):
    _abstraction_fake(monkeypatch, "unifiedAccount")
    st = HlVenue().account_state("0xabc")
    assert st["abstraction"] == "unifiedAccount"
    assert st["available"] == {"": 844_000.0, "xyz": 844_000.0}   # not the $5.7k withdrawable


def test_portfolio_margin_also_uses_spot_usdc_free(monkeypatch):
    _abstraction_fake(monkeypatch, "portfolioMargin")
    st = HlVenue().account_state("0xabc")
    assert st["abstraction"] == "portfolioMargin"
    assert st["available"][""] == 844_000.0


def test_standard_account_keeps_per_dex_withdrawable(monkeypatch):
    _abstraction_fake(monkeypatch, "disabled")
    st = HlVenue().account_state("0xabc")
    assert st["abstraction"] == "disabled"
    assert st["available"] == {"": 5_700.0, "xyz": 0.0}


def test_abstraction_read_failure_omits_key_and_keeps_withdrawable(monkeypatch):
    _abstraction_fake(monkeypatch, None)
    st = HlVenue().account_state("0xabc")
    assert st is not None                         # never fails the whole read
    assert "abstraction" not in st
    assert st["available"] == {"": 5_700.0, "xyz": 0.0}


def test_abstraction_unexpected_shape_is_a_failed_read(monkeypatch):
    _abstraction_fake(monkeypatch, {"error": "nope"})
    st = HlVenue().account_state("0xabc")
    assert st is not None and "abstraction" not in st


def test_abstraction_cached_per_user_then_refreshed_after_ttl(monkeypatch):
    calls = []
    _abstraction_fake(monkeypatch, "unifiedAccount", calls)
    v = HlVenue()
    v.account_state("0xabc")
    v.account_state("0xabc")
    assert calls.count("userAbstraction") == 1
    key, (val, ts) = next(iter(venue_mod._abstraction.items()))
    venue_mod._abstraction[key] = (val, ts - venue_mod.ABSTRACTION_TTL_S - 1)
    v.account_state("0xabc")
    assert calls.count("userAbstraction") == 2


def test_abstraction_failure_after_success_serves_last_known(monkeypatch):
    _abstraction_fake(monkeypatch, "unifiedAccount")
    v = HlVenue()
    v.account_state("0xabc")
    key, (val, ts) = next(iter(venue_mod._abstraction.items()))
    venue_mod._abstraction[key] = (val, ts - venue_mod.ABSTRACTION_TTL_S - 1)   # expired
    _abstraction_fake(monkeypatch, None)                                         # and now failing
    st = v.account_state("0xabc")
    assert st["abstraction"] == "unifiedAccount"
    assert st["available"][""] == 844_000.0
