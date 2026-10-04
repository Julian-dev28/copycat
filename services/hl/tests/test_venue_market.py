"""Gate tests for HlVenue.market_stats / depth_usd (contract v5): per-dex
metaAndAssetCtxs routing for HIP-3 coins, one call serving every coin on a
dex, TTL expiry, failure paths, and the depth band math. No network.
"""
from __future__ import annotations

import pytest
from hl import meta
from hl import venue as venue_mod
from hl.venue import HlVenue, _depth_within


def _ctx_response(rows):
    """rows: [(name, maxLeverage, ctx dict)] -> real metaAndAssetCtxs shape."""
    return [{"universe": [{"name": n, "szDecimals": 3, "maxLeverage": lev} for n, lev, _ in rows]},
            [c for _, _, c in rows]]


MAIN = _ctx_response([
    ("BTC", 40, {"markPx": "60000.0", "midPx": "60001.0", "dayNtlVlm": "1000000000.5",
                 "openInterest": "10.0"}),
    ("ETH", 25, {"markPx": "3000.0", "midPx": None, "dayNtlVlm": "5000", "openInterest": "2"}),
    ("DEAD", 3, {"markPx": None, "midPx": None, "dayNtlVlm": "0", "openInterest": "0"}),
])
XYZ = _ctx_response([
    ("xyz:TSLA", 20, {"markPx": "371.4", "midPx": "371.41", "dayNtlVlm": "21044982.93",
                      "openInterest": "100.0"}),
])


def _router(calls, main=MAIN, xyz=XYZ):
    def fake_post(path, payload, **kw):
        calls.append(dict(payload))
        if payload.get("type") != "metaAndAssetCtxs":
            return None
        return {"": main, "xyz": xyz}.get(payload.get("dex", ""))
    return fake_post


# ── market_stats ─────────────────────────────────────────────────────────────

def test_market_stats_main_coin_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _router(calls))
    s = HlVenue().market_stats("BTC")
    assert s == {"mark_px": 60000.0, "mid_px": 60001.0, "day_volume_usd": 1000000000.5,
                 "open_interest_usd": 600000.0, "max_leverage": 40}
    assert calls == [{"type": "metaAndAssetCtxs"}]   # main dex: no dex param


def test_market_stats_hip3_coin_reads_its_own_dex(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _router(calls))
    s = HlVenue().market_stats("xyz:TSLA")
    assert s["max_leverage"] == 20
    assert s["open_interest_usd"] == pytest.approx(37140.0)
    assert calls == [{"type": "metaAndAssetCtxs", "dex": "xyz"}]


def test_market_stats_one_call_serves_every_coin_on_a_dex(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _router(calls))
    v = HlVenue()
    v.market_stats("BTC")
    v.market_stats("ETH")
    v.market_stats("BTC")
    v.market_stats("xyz:TSLA")
    v.market_stats("xyz:TSLA")
    assert [c.get("dex", "") for c in calls] == ["", "xyz"]


def test_market_stats_refetches_after_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _router(calls))
    clock = [1000.0]
    monkeypatch.setattr(meta.time, "time", lambda: clock[0])
    v = HlVenue()
    v.market_stats("BTC")
    clock[0] += meta.ASSET_CTX_TTL_S - 1
    v.market_stats("BTC")
    assert len(calls) == 1
    clock[0] += 2
    v.market_stats("BTC")
    assert len(calls) == 2


def test_market_stats_mid_falls_back_to_mark(monkeypatch):
    monkeypatch.setattr(meta, "http_post", _router([]))
    assert HlVenue().market_stats("ETH")["mid_px"] == 3000.0


def test_market_stats_none_for_coin_without_mark(monkeypatch):
    monkeypatch.setattr(meta, "http_post", _router([]))
    assert HlVenue().market_stats("DEAD") is None


def test_market_stats_none_for_unknown_coin(monkeypatch):
    monkeypatch.setattr(meta, "http_post", _router([]))
    assert HlVenue().market_stats("NOPE") is None
    assert HlVenue().market_stats("xyz:NOPE") is None


@pytest.mark.parametrize("bad", [None, {}, [], [{"universe": []}], ["x", []], [{"universe": "x"}, []]])
def test_market_stats_none_on_failed_or_malformed_read(monkeypatch, bad):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: bad)
    assert HlVenue().market_stats("BTC") is None


def test_market_stats_failure_is_not_cached(monkeypatch):
    responses = [None, MAIN]
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: responses.pop(0))
    v = HlVenue()
    assert v.market_stats("BTC") is None
    assert v.market_stats("BTC")["mark_px"] == 60000.0


def test_market_stats_returns_a_copy(monkeypatch):
    monkeypatch.setattr(meta, "http_post", _router([]))
    v = HlVenue()
    v.market_stats("BTC")["mark_px"] = -1
    assert v.market_stats("BTC")["mark_px"] == 60000.0


def test_market_stats_without_faked_http_is_none():
    # conftest's _NoNetwork: http_post returns None -> market_stats None, no raise
    assert HlVenue().market_stats("BTC") is None


# ── depth math ───────────────────────────────────────────────────────────────

def _lv(*pairs):
    return [{"px": str(p), "sz": str(s), "n": 1} for p, s in pairs]


# bids 99.5 / 99 / 98, asks 100.5 / 101 / 102 -> mid 100.0
BOOK = [_lv((99.5, 1), (99, 2), (98, 10)), _lv((100.5, 1), (101, 2), (102, 10))]


def test_depth_buy_sums_asks_within_band():
    # bound 101.0 (inclusive): 100.5*1 + 101*2
    assert _depth_within(BOOK, True, 1.0) == pytest.approx(302.5)


def test_depth_sell_sums_bids_within_band():
    # bound 99.0 (inclusive): 99.5*1 + 99*2
    assert _depth_within(BOOK, False, 1.0) == pytest.approx(297.5)


def test_depth_wide_band_takes_every_level():
    assert _depth_within(BOOK, True, 50) == pytest.approx(100.5 + 202 + 1020)
    assert _depth_within(BOOK, False, 50) == pytest.approx(99.5 + 198 + 980)


def test_depth_band_tighter_than_spread_is_zero():
    assert _depth_within(BOOK, True, 0.1) == 0.0
    assert _depth_within(BOOK, False, 0.0) == 0.0


@pytest.mark.parametrize("levels", [
    None, [], [[]], [[], _lv((100.5, 1))], [_lv((99.5, 1)), []],
    [[{"px": "x", "sz": "1"}], _lv((100.5, 1))], [[{"sz": "1"}], _lv((100.5, 1))],
])
def test_depth_none_on_bad_or_one_sided_book(levels):
    assert _depth_within(levels, True, 1.0) is None


def test_depth_none_on_negative_pct():
    assert _depth_within(BOOK, True, -1) is None


# ── depth_usd (l2Book fetch + 2s cache) ─────────────────────────────────────

def _book_router(calls, book=BOOK):
    def fake_post(path, payload, **kw):
        calls.append(dict(payload))
        return {"coin": payload.get("coin"), "time": 1, "levels": book} if payload.get("type") == "l2Book" else None
    return fake_post


def test_depth_usd_hip3_coin_uses_full_name(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _book_router(calls))
    assert HlVenue().depth_usd("xyz:TSLA", True, 1.0) == pytest.approx(302.5)
    assert calls == [{"type": "l2Book", "coin": "xyz:TSLA"}]


def test_depth_usd_caches_book_across_sides_and_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "http_post", _book_router(calls))
    clock = [1000.0]
    monkeypatch.setattr(meta.time, "time", lambda: clock[0])
    v = HlVenue()
    v.depth_usd("BTC", True, 1.0)
    v.depth_usd("BTC", False, 0.5)
    assert len(calls) == 1
    v.depth_usd("ETH", True, 1.0)
    assert len(calls) == 2          # cache is per coin
    clock[0] += meta.L2_BOOK_TTL_S + 0.1
    v.depth_usd("BTC", True, 1.0)
    assert len(calls) == 3


@pytest.mark.parametrize("bad", [None, {}, {"levels": None}, {"levels": [[]]}, {"levels": "x"}, []])
def test_depth_usd_none_on_failed_read(monkeypatch, bad):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: bad)
    assert HlVenue().depth_usd("BTC", True, 1.0) is None


def test_depth_usd_failure_is_not_cached(monkeypatch):
    responses = [None, {"levels": BOOK}]
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: responses.pop(0))
    v = HlVenue()
    assert v.depth_usd("BTC", True, 1.0) is None
    assert v.depth_usd("BTC", True, 1.0) == pytest.approx(302.5)


def test_depth_usd_never_raises(monkeypatch):
    def boom(coin, force_refresh=False):
        raise RuntimeError("x")
    monkeypatch.setattr(venue_mod.meta, "l2_book", boom)
    assert HlVenue().depth_usd("BTC", True, 1.0) is None
