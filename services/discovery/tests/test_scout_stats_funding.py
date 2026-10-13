"""Stage B wiring for round-trip funding (user research P0): CountingVenue
charges and exposes `funding` only when the wrapped venue has it, and
build_wallet nets real funding into the stored round trips end to end."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from discovery.scout import stats, store
from test_scout_helpers import DAY, NOW, ScoutVenue, addr, fill, portfolio


class FundingScoutVenue(ScoutVenue):
    def __init__(self) -> None:
        super().__init__()
        self._funding: Dict[str, List[Dict[str, Any]]] = {}
        self.funding_calls: List[tuple] = []

    def set_funding(self, user: str, rows: List[Dict[str, Any]]) -> None:
        self._funding[user] = rows

    def funding(self, user: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]:
        self.funding_calls.append((user, start_ms, end_ms))
        rows = self._funding.get(user, [])
        return [r for r in rows if start_ms <= r["time_ms"] <= end_ms]


def test_counting_venue_exposes_funding_only_when_the_wrapped_venue_has_it():
    plain = stats.CountingVenue(ScoutVenue())
    assert not hasattr(plain, "funding")
    wired = stats.CountingVenue(FundingScoutVenue())
    assert hasattr(wired, "funding")


def test_counting_venue_charges_funding_pages():
    v = FundingScoutVenue()
    v.set_funding("0xabc", [{"time_ms": 1, "coin": "BTC", "usdc": -1.0, "funding_rate": 0.0}])
    cv = stats.CountingVenue(v)
    out = cv.funding("0xabc", 0, 1000)
    assert out and cv.weight > 0 and cv.calls["funding"] == 1


def test_build_wallet_nets_real_funding_into_stored_round_trips(tmp_path):
    conn = store.connect(tmp_path / "funding_stats.db")
    A = addr(1)
    v = FundingScoutVenue()
    opened, closed = NOW - 10 * DAY, NOW - 9 * DAY
    v.set_fills(A, [
        fill(opened, "BTC", 100.0, 2.0, "B", 0.0, fee=0.2),
        fill(closed, "BTC", 110.0, 2.0, "A", 2.0, pnl=20.0, fee=0.2),
    ])
    v.set_funding(A, [
        {"time_ms": opened + 3_600_000, "coin": "BTC", "usdc": -1.5, "funding_rate": 0.0000125},
        {"time_ms": closed + 3_600_000, "coin": "BTC", "usdc": 999.0, "funding_rate": 0.0000125},  # after close
    ])
    v.set_portfolio(A, portfolio([0] * 31, av=20_000.0))
    v.set_account_state(A, {"equity_perp_usd": 20_000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    assert v.funding_calls   # the wallet's funding was actually fetched, not silently skipped

    st = store.stats_row(conn, A)
    import json
    trips = json.loads(st["stats_json"])["recent_trips"]
    assert len(trips) == 1
    t = trips[0]
    assert t["gross_pnl_usd"] == pytest.approx(20.0)
    assert t["fee_usd"] == pytest.approx(0.4)
    assert t["funding_usd"] == pytest.approx(-1.5)          # the post-close row is excluded
    assert t["net_pnl_usd"] == pytest.approx(20.0 - 0.4 - 1.5)
    assert "funding_unavailable" not in json.loads(st["stats_json"])["flags"]


def test_build_wallet_flags_funding_unavailable_on_a_failed_read(tmp_path, monkeypatch):
    conn = store.connect(tmp_path / "funding_stats2.db")
    A = addr(2)
    v = FundingScoutVenue()
    v.set_fills(A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    v.set_portfolio(A, portfolio([0] * 31, av=20_000.0))
    v.set_account_state(A, {"equity_perp_usd": 20_000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})

    def failing(user: str, start_ms: int, end_ms: int):
        return None

    monkeypatch.setattr(v, "funding", failing)
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    import json
    st = store.stats_row(conn, A)
    assert "funding_unavailable" in json.loads(st["stats_json"])["flags"]
