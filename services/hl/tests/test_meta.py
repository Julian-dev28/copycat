"""Gate tests for hl.meta: universe caching + stale fallback, the
never-silently-1 max_leverage contract, is_isolated_only's default, the
dex list, and spot price lookup by universe `index` (not list position)
with the illiquid-mark exclusion input it feeds. No network.
"""
from __future__ import annotations

from hl import meta


def _meta_response(universe):
    return {"universe": universe}


# ── universe() caching ───────────────────────────────────────────────────────

def test_universe_caches_and_serves_without_a_second_call(monkeypatch):
    calls = []

    def fake_post(path, payload, **kw):
        calls.append(payload)
        return _meta_response([{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}])

    monkeypatch.setattr(meta, "http_post", fake_post)
    u1 = meta.universe()
    u2 = meta.universe()
    assert u1 == u2
    assert len(calls) == 1  # second call served from cache


def test_universe_serves_stale_cache_on_fetch_failure(monkeypatch):
    responses = [_meta_response([{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]), None]

    def fake_post(path, payload, **kw):
        return responses.pop(0)

    monkeypatch.setattr(meta, "http_post", fake_post)
    good = meta.universe()
    assert good[0]["name"] == "BTC"
    stale = meta.universe(force_refresh=True)  # fetch fails this time
    assert stale == good  # served the stale cache, not an empty list


def test_universe_empty_list_when_no_cache_and_fetch_fails(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: None)
    assert meta.universe() == []


def test_universe_passes_dex_param_only_when_set(monkeypatch):
    seen = {}

    def fake_post(path, payload, **kw):
        seen.update(payload)
        return _meta_response([])

    monkeypatch.setattr(meta, "http_post", fake_post)
    meta.universe()
    assert "dex" not in seen
    meta.universe(dex="xyz")
    assert seen["dex"] == "xyz"


# ── max_leverage: never silently 1 ──────────────────────────────────────────

def test_max_leverage_happy_path(monkeypatch):
    monkeypatch.setattr(meta, "http_post",
                         lambda path, payload, **kw: _meta_response([{"name": "BTC", "maxLeverage": 40}]))
    assert meta.max_leverage("BTC") == 40


def test_max_leverage_returns_0_not_1_when_coin_unknown(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: _meta_response([]))
    assert meta.max_leverage("NOPE") == 0


def test_max_leverage_returns_0_not_1_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: None)
    assert meta.max_leverage("BTC") == 0


def test_max_leverage_forces_hip3_refresh_when_cached_entry_missing_leverage(monkeypatch):
    """The 2026-09-08 pathiel incident: a HIP-3 coin's cached meta entry
    was present but missing `maxLeverage` (a cold/partial warm). The old
    code returned 1 silently. The fix forces ONE refresh before giving up
    -- this test proves that refresh happens and finds the real value."""
    calls = {"n": 0}

    def fake_post(path, payload, **kw):
        calls["n"] += 1
        if payload.get("dex") == "xyz" and calls["n"] == 1:
            # first (cached) read: entry present but maxLeverage missing/0
            return _meta_response([{"name": "xyz:TSLA", "maxLeverage": 0}])
        if payload.get("dex") == "xyz":
            # forced refresh: the real value
            return _meta_response([{"name": "xyz:TSLA", "maxLeverage": 10}])
        return _meta_response([])  # main dex: coin not found there

    monkeypatch.setattr(meta, "http_post", fake_post)
    assert meta.max_leverage("xyz:TSLA") == 10
    assert calls["n"] >= 2  # proves the forced refresh actually happened


def test_max_leverage_unparseable_entry_treated_as_unknown(monkeypatch):
    monkeypatch.setattr(meta, "http_post",
                         lambda path, payload, **kw: _meta_response([{"name": "BTC", "maxLeverage": "garbage"}]))
    assert meta.max_leverage("BTC") == 0


# ── is_isolated_only ─────────────────────────────────────────────────────────

def test_is_isolated_only_true(monkeypatch):
    monkeypatch.setattr(meta, "http_post",
                         lambda path, payload, **kw: _meta_response([{"name": "xyz:HOOD", "onlyIsolated": True}]))
    assert meta.is_isolated_only("xyz:HOOD") is True


def test_is_isolated_only_defaults_false_on_failure(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: None)
    assert meta.is_isolated_only("BTC") is False


def test_is_isolated_only_defaults_false_for_unknown_coin(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: _meta_response([]))
    assert meta.is_isolated_only("BTC") is False


# ── dex_list ──────────────────────────────────────────────────────────────────

def test_dex_list_defaults_to_main_plus_perp_dexs(monkeypatch):
    monkeypatch.setattr(meta, "http_post",
                         lambda path, payload, **kw: [None, {"name": "xyz"}, {"name": "vntl"}])
    assert meta.dex_list() == ["", "xyz", "vntl"]


def test_dex_list_env_override(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_DEXES", ",xyz")
    assert meta.dex_list() == ["", "xyz"]


def test_dex_list_explicit_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_DEXES", ",xyz")
    assert meta.dex_list(override=["", "vntl"]) == ["", "vntl"]


def test_perp_dexs_excludes_null_main_entry(monkeypatch):
    monkeypatch.setattr(meta, "http_post",
                         lambda path, payload, **kw: [None, {"name": "xyz"}])
    assert meta.perp_dexs() == ["xyz"]


def test_perp_dexs_serves_stale_list_on_empty_response(monkeypatch):
    responses = [[None, {"name": "xyz"}], []]
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: responses.pop(0))
    first = meta.perp_dexs()
    stale = meta.perp_dexs(force_refresh=True)
    assert first == stale == ["xyz"]


# ── spot_prices: index-based lookup + dayNtlVlm passthrough ────────────────

def test_spot_prices_uses_universe_index_not_list_position(monkeypatch):
    """universe[i]["index"] must address ctxs -- NOT the enumerate position
    `i`. This payload puts PURR's universe entry FIRST in the list but
    gives it ctx `index`=1, and HYPE's entry SECOND but `index`=0, so a
    naive enumerate-position lookup would swap their prices/volumes."""
    tokens = [
        {"index": 0, "name": "USDC"},
        {"index": 1, "name": "PURR"},
        {"index": 2, "name": "HYPE"},
    ]
    universe = [
        {"tokens": [1, 0], "name": "PURR/USDC", "index": 1},  # PURR's ctx is ctxs[1]
        {"tokens": [2, 0], "name": "HYPE/USDC", "index": 0},  # HYPE's ctx is ctxs[0]
    ]
    ctxs = [
        {"midPx": "30.0", "dayNtlVlm": "1000000"},   # index 0 -> HYPE's real data
        {"midPx": "0.16", "dayNtlVlm": "500000"},    # index 1 -> PURR's real data
    ]
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: [{"tokens": tokens, "universe": universe}, ctxs])
    prices = meta.spot_prices()
    assert prices["PURR"] == (0.16, 500000.0)
    assert prices["HYPE"] == (30.0, 1000000.0)


def test_spot_prices_falls_back_to_markPx(monkeypatch):
    tokens = [{"index": 0, "name": "USDC"}, {"index": 1, "name": "FOO"}]
    universe = [{"tokens": [1, 0], "name": "FOO/USDC", "index": 0}]
    ctxs = [{"midPx": None, "markPx": "2.5", "dayNtlVlm": "100"}]
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: [{"tokens": tokens, "universe": universe}, ctxs])
    assert meta.spot_prices()["FOO"] == (2.5, 100.0)


def test_spot_prices_none_on_bad_shape(monkeypatch):
    monkeypatch.setattr(meta, "http_post", lambda path, payload, **kw: {"not": "a list of 2"})
    assert meta.spot_prices() is None


def test_spot_prices_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_post(path, payload, **kw):
        calls["n"] += 1
        tokens = [{"index": 0, "name": "USDC"}]
        return [{"tokens": tokens, "universe": []}, []]

    monkeypatch.setattr(meta, "http_post", fake_post)
    meta.spot_prices()
    meta.spot_prices()
    assert calls["n"] == 1
