"""Gate tests for contract v3 reads: HlVenue.portfolio, HlVenue.open_orders,
and the pure hl.leaderboard.parse_rows helper. Fake http_post, no network.
"""
from __future__ import annotations

import math

from hl import meta
from hl import venue as venue_mod
from hl.leaderboard import parse_row, parse_rows
from hl.rate_limit import endpoint_weight
from hl.venue import HlVenue

U = "0xe2823659be02e0f48a4660e4da008b5e1abfdf29"


# ── weights ──────────────────────────────────────────────────────────────────

def test_portfolio_and_frontend_open_orders_weigh_20():
    # HL docs: everything not in the weight-2 / weight-60 lists is 20.
    assert endpoint_weight("portfolio") == 20
    assert endpoint_weight("frontendOpenOrders") == 20


# ── portfolio ────────────────────────────────────────────────────────────────

def _portfolio_body():
    w = {"accountValueHistory": [[1, "100.0"], [2, "110.0"]],
         "pnlHistory": [[1, "0.0"], [2, "10.0"]], "vlm": "500.0"}
    return [[label, dict(w)] for label in
            ("day", "week", "month", "allTime", "perpDay", "perpWeek", "perpMonth", "perpAllTime")]


def test_portfolio_returns_raw_list_and_sends_right_payload(monkeypatch):
    seen = []
    body = _portfolio_body()

    def fake_post(path, payload, **kw):
        seen.append((path, payload))
        return body

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    assert HlVenue().portfolio(U) == body
    assert seen == [("/info", {"type": "portfolio", "user": U})]


def test_portfolio_none_on_failed_read(monkeypatch):
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: None)
    assert HlVenue().portfolio(U) is None


def test_portfolio_none_on_bad_shape(monkeypatch):
    for bad in ({"day": {}}, [["day"]], [[1, {}]], [["day", "x"]], "oops"):
        monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, _b=bad, **kw: _b)
        assert HlVenue().portfolio(U) is None, bad


def test_portfolio_empty_list_is_valid(monkeypatch):
    # A never-traded address: HL answers with a list; empty is not a failure.
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: [])
    assert HlVenue().portfolio(U) == []


def test_portfolio_never_raises(monkeypatch):
    def boom(path, payload, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(venue_mod, "http_post", boom)
    assert HlVenue().portfolio(U) is None


# ── open_orders ──────────────────────────────────────────────────────────────

def _order(coin, oid=1):
    return {"coin": coin, "side": "A", "limitPx": "100.0", "sz": "1.0", "oid": oid,
            "timestamp": 1, "isTrigger": False, "reduceOnly": False, "orderType": "Limit",
            "origSz": "1.0", "tif": "Gtc", "cloid": None, "children": []}


def test_open_orders_across_dexes_namespaces_hip3(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz", "flx"])
    seen = []

    def fake_post(path, payload, **kw):
        assert payload["type"] == "frontendOpenOrders" and payload["user"] == U
        seen.append(payload["dex"])
        return {"": [_order("BTC", 1)], "xyz": [_order("TSLA", 2), _order("xyz:NVDA", 3)], "flx": []}[payload["dex"]]

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    out = HlVenue().open_orders(U)
    assert seen == ["", "xyz", "flx"]   # cold cache: full scan
    assert [o["coin"] for o in out] == ["BTC", "xyz:TSLA", "xyz:NVDA"]   # never "xyz:xyz:NVDA"
    assert out[1]["oid"] == 2 and out[1]["limitPx"] == "100.0"           # otherwise raw


def test_open_orders_does_not_mutate_hl_rows(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["xyz"])
    raw = [_order("TSLA")]
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: raw)
    HlVenue().open_orders(U)
    assert raw[0]["coin"] == "TSLA"


def test_open_orders_none_if_any_dex_fails(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])
    monkeypatch.setattr(venue_mod, "http_post",
                        lambda path, payload, **kw: [_order("BTC")] if payload["dex"] == "" else None)
    assert HlVenue().open_orders(U) is None


def test_open_orders_none_on_non_dict_row(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: [""])
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: ["junk"])
    assert HlVenue().open_orders(U) is None


def test_open_orders_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("dex list down")

    monkeypatch.setattr(meta, "dex_list", boom)
    assert HlVenue().open_orders(U) is None


def test_open_orders_empty_everywhere_is_empty_list(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: [])
    assert HlVenue().open_orders(U) == []


def test_open_orders_reuses_active_dex_cache(monkeypatch):
    """After account_state's full scan found the user only on main + xyz,
    open_orders reads just those two, not every dex."""
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz", "flx", "km"])

    def acct_post(path, payload, **kw):
        t = payload["type"]
        if t == "clearinghouseState":
            pos = [{"position": {"coin": "TSLA", "szi": "1", "entryPx": "1",
                                 "leverage": {"type": "isolated", "value": 2}}}]
            return {"marginSummary": {"accountValue": "0"}, "withdrawable": "0",
                    "assetPositions": pos if payload["dex"] == "xyz" else []}
        if t == "spotClearinghouseState":
            return {"balances": []}
        return None   # userAbstraction

    monkeypatch.setattr(venue_mod, "http_post", acct_post)
    assert HlVenue().account_state(U) is not None

    seen = []

    def oo_post(path, payload, **kw):
        seen.append(payload["dex"])
        return []

    monkeypatch.setattr(venue_mod, "http_post", oo_post)
    assert HlVenue().open_orders(U) == []
    assert seen == ["", "xyz"]


def test_open_orders_records_order_dexes_without_resetting_rescan(monkeypatch):
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz", "flx"])
    monkeypatch.setattr(venue_mod, "http_post",
                        lambda path, payload, **kw: [_order("GOLD")] if payload["dex"] == "flx" else [])
    out = HlVenue().open_orders(U)
    assert [o["coin"] for o in out] == ["flx:GOLD"]
    assert venue_mod._active_dexes[U] == ["flx"]
    # open_orders never claims a full scan: account_state still does its own.
    assert U not in venue_mod._last_full_scan


def test_open_orders_respects_pinned_dexes(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_DEXES", ",xyz")
    monkeypatch.setattr(meta, "dex_list", lambda: ["", "xyz"])
    seen = []
    monkeypatch.setattr(venue_mod, "http_post",
                        lambda path, payload, **kw: seen.append(payload["dex"]) or [])
    HlVenue().open_orders(U)
    assert seen == ["", "xyz"]


# ── hl.leaderboard.parse_rows ────────────────────────────────────────────────

ADDR = "0x85ECF584F25DB6F146718B86D493E33C5AF72052"


def _lb_row(**over):
    row = {
        "ethAddress": ADDR,
        "accountValue": "62330451.1721990108",
        "windowPerformances": [
            ["day", {"pnl": "310963.157278", "roi": "0.0055071207", "vlm": "1450003736.8299999237"}],
            ["week", {"pnl": "2852804.9591829996", "roi": "0.0512880601", "vlm": "9048872792.98"}],
            ["month", {"pnl": "-960491.26", "roi": "-0.014177401", "vlm": "40991110551.94"}],
            ["allTime", {"pnl": "5486773.72", "roi": "0.0456111172", "vlm": "218905315448.54"}],
        ],
        "prize": 0,
        "displayName": None,
    }
    row.update(over)
    return row


def test_parse_rows_types_every_number():
    [p] = parse_rows([_lb_row(displayName="whale")])
    assert p["address"] == ADDR.lower()
    assert p["display_name"] == "whale"
    assert math.isclose(p["account_value"], 62330451.1721990108)
    assert p["day"] == {"pnl": 310963.157278, "roi": 0.0055071207, "vlm": 1450003736.8299999237}
    assert p["month"]["pnl"] == -960491.26 and p["month"]["roi"] == -0.014177401
    assert set(p) == {"address", "display_name", "account_value", "day", "week", "month", "allTime"}
    for w in ("day", "week", "month", "allTime"):
        assert all(isinstance(v, float) for v in p[w].values())


def test_parse_rows_display_name_null_or_empty_is_none():
    assert parse_rows([_lb_row(displayName=None)])[0]["display_name"] is None
    assert parse_rows([_lb_row(displayName="")])[0]["display_name"] is None


def test_parse_rows_window_order_does_not_matter():
    row = _lb_row()
    row["windowPerformances"] = list(reversed(row["windowPerformances"]))
    assert parse_rows([row])[0]["day"]["pnl"] == 310963.157278


def test_parse_rows_accepts_numeric_values_too():
    row = _lb_row(accountValue=100)
    assert parse_rows([row])[0]["account_value"] == 100.0


def test_parse_rows_drops_malformed_rows_never_zero_fills():
    missing_window = _lb_row()
    missing_window["windowPerformances"] = missing_window["windowPerformances"][:3]
    bad_number = _lb_row()
    bad_number["windowPerformances"][0][1]["pnl"] = "abc"
    nan = _lb_row(accountValue="NaN")
    none_val = _lb_row(accountValue=None)
    bool_val = _lb_row(accountValue=True)
    bad_addr = _lb_row(ethAddress="0x123")
    no_wp = _lb_row(windowPerformances={"day": {}})
    good = _lb_row()
    out = parse_rows([missing_window, bad_number, nan, none_val, bool_val, bad_addr, no_wp,
                      "junk", None, good])
    assert len(out) == 1 and out[0]["address"] == ADDR.lower()


def test_parse_rows_non_list_input_is_empty():
    assert parse_rows(None) == []
    assert parse_rows("x") == []
    assert parse_rows([]) == []


def test_parse_rows_accepts_whole_response_body():
    assert len(parse_rows({"leaderboardRows": [_lb_row()]})) == 1
    assert parse_rows({"nope": []}) == []


def test_parse_row_ignores_extra_windows():
    row = _lb_row()
    row["windowPerformances"].append(["year", {"pnl": "1", "roi": "1", "vlm": "1"}])
    p = parse_row(row)
    assert p is not None and "year" not in p
