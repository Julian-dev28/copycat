"""CountingVenue bills a paginated read what HL metered for it, not the page
cap (indexing tightening follow-up, 2026-10-15): a 12-row warm tail costs
21, a full 2000-row page 120. Until this change every page was billed 120,
so the budget eval's warm-pass check (evals/stats_budget_check.py, warm p50
<= 60 weight/wallet) could not pass with a correct warm path: portfolio 20
+ one tail page 120 = 140 was the floor. tests/invariants/test_hl_weights.py
pins the rule here to hl.rate_limit's own."""
from __future__ import annotations

import math

from discovery.scout import config as C
from discovery.scout import stats, store
from discovery_fakes import FakeFundingVenue
from test_scout_helpers import DAY, HOUR, NOW, ScoutVenue, addr, fill, portfolio


def _tail(a: str, n: int, start: int = NOW - DAY):
    return [fill(start + i * 1000, "BTC", 100.0, 1.0, "B", 0.0) for i in range(n)]


class RecordingVenue(ScoutVenue):
    """Like HlVenue: publishes what its last paginated read cost."""

    def __init__(self) -> None:
        super().__init__()
        self.last_read = None

    def fills(self, user, start_ms, end_ms):
        rows = super().fills(user, start_ms, end_ms)
        self.last_read = {"type": "userFillsByTime", "pages": 2, "rows": 2012, "weight": 141}
        return rows


def test_a_warm_tail_is_billed_by_its_rows_not_the_page_cap():
    v = ScoutVenue()
    A = addr(1)
    v.set_fills(A, _tail(A, 12))
    cv = stats.CountingVenue(v)
    cv.fills(A, 0, NOW)
    assert cv.weight_by["fills"] == C.W_INFO + 1 == 21      # 20 base + ceil(12 / 20)
    assert cv.pages_by["fills"] == 1


def test_an_empty_tail_still_costs_the_base_weight_of_one_page():
    cv = stats.CountingVenue(ScoutVenue())
    cv.fills(addr(2), 0, NOW)
    assert cv.weight_by["fills"] == C.W_INFO and cv.pages_by["fills"] == 1


def test_a_full_page_costs_exactly_what_the_estimate_admits_against():
    v = ScoutVenue()
    A = addr(3)
    v.set_fills(A, _tail(A, C.FILLS_PAGE_ROWS))
    cv = stats.CountingVenue(v)
    cv.fills(A, 0, NOW)
    assert cv.weight_by["fills"] == C.W_FILLS_PAGE == 120

    v.set_fills(A, _tail(A, C.FILLS_PAGE_ROWS + 1))        # one row over: a second page, 20 + 1
    cv = stats.CountingVenue(v)
    cv.fills(A, 0, NOW)
    assert cv.weight_by["fills"] == 2 * C.W_INFO + math.ceil((C.FILLS_PAGE_ROWS + 1) / C.ITEMS_PER_WEIGHT) == 141
    assert cv.pages_by["fills"] == 2


def test_funding_pages_follow_the_same_rule():
    v = FakeFundingVenue()
    A = addr(4)
    v.set_funding(A, [{"time_ms": NOW - DAY + i * 1000, "coin": "BTC", "usdc": -0.1, "funding_rate": 0.0}
                      for i in range(C.FUNDING_PAGE_ROWS)])
    cv = stats.CountingVenue(v)
    cv.funding(A, 0, NOW)
    assert cv.weight_by["funding"] == C.W_FUNDING_PAGE == 45
    assert cv.pages_by["funding"] == 1

    v.set_funding(A, [{"time_ms": NOW - DAY, "coin": "BTC", "usdc": -0.1, "funding_rate": 0.0}] * 3)
    cv = stats.CountingVenue(v)
    cv.funding(A, 0, NOW)
    assert cv.weight_by["funding"] == C.W_INFO + 1


def test_the_venues_own_metered_count_wins_when_it_has_one():
    v = RecordingVenue()
    A = addr(5)
    v.set_fills(A, _tail(A, 3))                                # 3 rows handed back, but HL metered 2 pages
    cv = stats.CountingVenue(v)
    cv.fills(A, 0, NOW)
    assert cv.weight_by["fills"] == 141 and cv.pages_by["fills"] == 2


def test_a_metered_count_from_another_endpoint_is_ignored():
    v = ScoutVenue()
    A = addr(6)
    v.set_fills(A, _tail(A, 12))
    v.last_read = {"type": "userFunding", "pages": 9, "rows": 9000, "weight": 9999}   # stale, not this read
    cv = stats.CountingVenue(v)
    cv.fills(A, 0, NOW)
    assert cv.weight_by["fills"] == 21 and cv.pages_by["fills"] == 1


def test_a_warm_wallet_is_portfolio_plus_a_cheap_tail(tmp_path):
    conn = store.connect(tmp_path / "warm.db")
    A = addr(7)
    v = ScoutVenue()
    v.set_portfolio(A, portfolio([0] * 31, av=20_000.0))
    v.set_account_state(A, {"equity_perp_usd": 20_000.0, "spot_usdc": 500.0, "positions": {}, "raw_positions": {}})
    v.set_fills(A, _tail(A, 12, start=NOW - 10 * DAY))
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)

    cv = stats.CountingVenue(v)
    stats.build_wallet(conn, cv, A, NOW + HOUR)
    _, lo, hi = v.fills_calls[-1]
    returned = sum(1 for f in v._fills[A] if lo <= f["time_ms"] <= hi)
    assert "account_state" not in cv.calls
    assert cv.weight == C.W_PORTFOLIO + C.W_INFO + math.ceil(returned / C.ITEMS_PER_WEIGHT)
    assert cv.weight <= 60      # the budget eval's warm p50 threshold is reachable by construction
    assert cv.pages_by == {"fills": 1}


def test_a_cache_only_candle_miss_is_not_billed():
    """simstage.CacheOnlyVenue answers every candle read with None and reads nothing
    from HL; CountingVenue used to bill W_CANDLES per miss anyway, so a cache-only
    stage C reported hundreds of weight for zero HL calls (live 2026-10-15 04:10:
    "weight C=12720") and burned the stage C budget on nothing."""
    from discovery.scout import simstage
    cv = stats.CountingVenue(simstage.CacheOnlyVenue())
    assert cv.candles("BTC", "15m", 0, 1) is None
    assert cv.weight == 0 and "candles" not in cv.weight_by

    class Real:
        def candles(self, coin, interval, start_ms, end_ms):
            return None                                  # a real read that failed (or was starved)

    cv = stats.CountingVenue(Real())
    cv.candles("BTC", "15m", 0, 1)
    assert cv.weight_by["candles"] == C.W_CANDLES         # a real attempt still counts
