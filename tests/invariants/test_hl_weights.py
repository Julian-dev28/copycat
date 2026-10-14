"""The scout's HL weight constants and its billing rule ARE hl's own rule
(services/hl/hl/rate_limit.py, the documented per-IP meter), so the stage-B
budget, the per-pass summary in scout_meta and the stats_budget_check eval
count the same units HL does. A drift here would make the budget admit the
wrong number of wallets per pass without anything crashing."""
from __future__ import annotations

import pytest
from discovery.scout import config as C
from discovery.scout import stats
from hl.rate_limit import endpoint_weight


class _Rows:
    """The smallest venue a CountingVenue can wrap: n rows back, no `last_read`."""

    def __init__(self, n: int) -> None:
        self.n = n

    def fills(self, user, start_ms, end_ms):
        return [{"time_ms": i} for i in range(self.n)]

    def funding(self, user, start_ms, end_ms):
        return [{"time_ms": i} for i in range(self.n)]


@pytest.mark.parametrize("n", [0, 1, 12, 19, 20, 21, 1999, 2000])
def test_one_page_of_fills_is_billed_what_hl_meters(n):
    cv = stats.CountingVenue(_Rows(n))
    cv.fills("0x", 0, 1)
    assert cv.weight_by["fills"] == endpoint_weight("userFillsByTime", n)


@pytest.mark.parametrize("n", [0, 1, 20, 21, 499, 500])
def test_one_page_of_funding_is_billed_what_hl_meters(n):
    cv = stats.CountingVenue(_Rows(n))
    cv.funding("0x", 0, 1)
    assert cv.weight_by["funding"] == endpoint_weight("userFunding", n)


def test_full_pages_plus_a_tail_match_hl_page_by_page():
    n = 2 * C.FILLS_PAGE_ROWS + 12
    cv = stats.CountingVenue(_Rows(n))
    cv.fills("0x", 0, 1)
    assert cv.pages_by["fills"] == 3
    assert cv.weight_by["fills"] == 2 * endpoint_weight("userFillsByTime", C.FILLS_PAGE_ROWS) \
        + endpoint_weight("userFillsByTime", 12)


def test_the_constants_are_hls_numbers():
    assert C.W_INFO == endpoint_weight("userFillsByTime", 0) == endpoint_weight("userFunding", 0)
    assert C.W_PORTFOLIO == endpoint_weight("portfolio")
    assert C.W_FILLS_PAGE == endpoint_weight("userFillsByTime", C.FILLS_PAGE_ROWS) == 120
    assert C.W_FUNDING_PAGE == endpoint_weight("userFunding", C.FUNDING_PAGE_ROWS) == 45
    assert endpoint_weight("userFillsByTime", C.ITEMS_PER_WEIGHT) == C.W_INFO + 1
    assert endpoint_weight("userFillsByTime", C.ITEMS_PER_WEIGHT + 1) == C.W_INFO + 2
