from __future__ import annotations

from discovery import candles_cache, db

from discovery_fakes import FakeVenue, flat_candles

M = 60_000
NOW = 10_000 * M   # far enough from 0 that tier math is exercised


def test_fetches_once_then_serves_from_coverage(conn):
    venue = FakeVenue()
    venue.set_candles("BTC", "1m", flat_candles(0, 300_000, 100.0))
    rows1 = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 180_000, now_ms=NOW)
    assert len(rows1) == 4
    assert len(venue.candles_calls) == 1
    candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 180_000, now_ms=NOW)
    assert len(venue.candles_calls) == 1
    rows2 = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 300_000, now_ms=NOW)
    assert len(rows2) == 6
    assert venue.candles_calls[1] == ("BTC", "1m", 180_001, 300_000)   # only the uncovered tail


def test_holes_hl_does_not_have_are_not_refetched_every_run(conn):
    """Regression: the old row-based gap check re-requested bars HL never
    returns (illiquid minutes, data older than HL's 5000-bar window) on
    every single run."""
    venue = FakeVenue()
    rows = [r for r in flat_candles(0, 600_000, 1.0) if r["t"] not in (120_000, 240_000)]
    venue.set_candles("xyz:THIN", "1m", rows)
    candles_cache.get_candles(conn, venue, "xyz:THIN", "1m", 0, 600_000, now_ms=NOW)
    candles_cache.get_candles(conn, venue, "xyz:THIN", "1m", 0, 600_000, now_ms=NOW)
    assert len(venue.candles_calls) == 1


def test_failed_fetch_records_no_coverage(conn):
    venue = FakeVenue()
    venue.fail_candles.add("BTC")
    assert not candles_cache.ensure_cached(conn, venue, "BTC", "1m", 0, 120_000, NOW)
    assert db.get_candle_coverage(conn, "BTC", "1m") == []
    venue.fail_candles.clear()
    venue.set_candles("BTC", "1m", flat_candles(0, 120_000, 1.0))
    assert candles_cache.ensure_cached(conn, venue, "BTC", "1m", 0, 120_000, NOW)
    assert len(venue.candles_calls) == 2


def test_forming_bar_is_refetched_and_replaced(conn):
    venue = FakeVenue()
    now = 600_000 + 30_000                                  # bar at 600_000 is still forming
    venue.set_candles("BTC", "1m", flat_candles(0, 600_000, 1.0))
    candles_cache.ensure_cached(conn, venue, "BTC", "1m", 0, now, now)
    final = flat_candles(0, 660_000, 1.0)
    final[10]["c"] = 2.0                                    # bar 600_000 closed at 2.0
    venue.set_candles("BTC", "1m", final)
    later = 700_000
    candles_cache.ensure_cached(conn, venue, "BTC", "1m", 0, later, later)
    assert venue.candles_calls[1][2] <= 600_000            # refetch includes the formerly forming bar
    assert db.get_cached_candles(conn, "BTC", "1m", 600_000, 600_000)[0]["c"] == 2.0


def test_tier_bounds_are_contiguous_and_aligned():
    now = 1_790_000_000_000
    b = candles_cache.tier_bounds(now)
    assert [iv for iv, _, _ in b] == ["1m", "15m", "1h"]
    (_, lo1, hi1), (_, lo15, hi15), (_, lo60, hi60) = b
    assert hi15 == lo1 and hi60 == lo15
    assert lo1 % 900_000 == 0 and lo15 % 3_600_000 == 0
    assert now - lo1 <= candles_cache.TIER_BARS * 60_000           # 1m only where HL still has it
    assert 3.3 < (now - lo1) / 86_400_000 < 3.5
    assert 50 < (now - lo15) / 86_400_000 < 52


def test_build_series_uses_1m_recently_and_15m_before(conn):
    import sqlite3
    venue = FakeVenue()
    now = 1_790_000_000_000
    (_, lo1, _), (_, lo15, _), _ = candles_cache.tier_bounds(now)
    start = lo1 - 2 * 3_600_000
    venue.set_candles("BTC", "15m", flat_candles(start - 900_000, lo1 + 86_400_000, 1.0, step_ms=900_000))
    venue.set_candles("BTC", "1m", flat_candles(lo1, lo1 + 3_600_000, 1.0))
    s, ok = candles_cache.build_series(conn, venue, "BTC", [(start, lo1 + 3_600_000)], now)
    assert ok
    assert all(t < lo1 for t, st in zip(s.t, s.step) if st == 900_000)
    assert all(t >= lo1 for t, st in zip(s.t, s.step) if st == 60_000)
    assert s.t == sorted(s.t)
    assert all(e <= n for e, n in zip(s.end, s.t[1:]))              # no overlaps
    assert {iv for _, iv, _, _ in venue.candles_calls} == {"1m", "15m"}
    assert isinstance(conn, sqlite3.Connection)
