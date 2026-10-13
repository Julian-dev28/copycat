"""funding_cache.sync_funding: coverage-tracked incremental sync (mirrors
test_fills_cache.py), plus the "venue doesn't implement funding" path that
has no fills_cache analog (funding is optional on contracts.venue.Venue)."""
from __future__ import annotations

import pytest
from discovery import db, funding_cache
from discovery_fakes import FakeFundingVenue, FakeVenue

DAY = 86_400_000


def frow(time_ms, coin="BTC", usdc=-0.5, rate=0.0000125):
    return {"time_ms": time_ms, "coin": coin, "usdc": usdc, "funding_rate": rate}


def test_no_op_when_the_venue_does_not_implement_funding(conn):
    """FakeVenue (no funding() method) is what every pre-existing scout test
    uses: sync_funding must not raise or require a fetch from it."""
    venue = FakeVenue()
    out = funding_cache.sync_funding(conn, venue, "0xabc", window_days=1, now_ms=100_000_000)
    assert out == []
    assert db.get_funding_coverage(conn, "0xabc") is None


def test_only_fetches_outside_coverage(conn):
    venue = FakeFundingVenue()
    w = "0xabc"
    venue.set_funding(w, [frow(14_000_000), frow(50_000_000)])
    out1 = funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=100_000_000)
    assert {f["time_ms"] for f in out1} == {14_000_000, 50_000_000}
    assert venue.funding_calls == [(w, 13_600_000, 100_000_000)]

    venue.set_funding(w, [frow(14_000_000), frow(50_000_000), frow(100_200_000)])
    out2 = funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=100_500_000)
    assert venue.funding_calls[1] == (w, 100_000_001, 100_500_000)
    assert 100_200_000 in {f["time_ms"] for f in out2}
    assert 14_000_000 not in {f["time_ms"] for f in out2}


def test_wider_window_backfills_only_the_older_part(conn):
    venue = FakeFundingVenue()
    w = "0xwide"
    now = 10 * DAY
    venue.set_funding(w, [frow(2 * DAY), frow(9 * DAY)])
    funding_cache.sync_funding(conn, venue, w, window_days=3, now_ms=now)
    out = funding_cache.sync_funding(conn, venue, w, window_days=9, now_ms=now)
    assert venue.funding_calls[1] == (w, 1 * DAY, 7 * DAY - 1)
    assert len(venue.funding_calls) == 2
    assert {f["time_ms"] for f in out} == {2 * DAY, 9 * DAY}


def test_failed_read_raises_and_leaves_coverage_untouched(conn):
    venue = FakeFundingVenue()
    w = "0xrate"
    venue.set_funding(w, [frow(5_000)])
    venue.fail_funding.add(w)
    with pytest.raises(funding_cache.FundingFetchError):
        funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=10_000)
    assert db.get_funding_coverage(conn, w) is None
    venue.fail_funding.clear()
    assert len(funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=10_000)) == 1


def test_fresh_coverage_skips_the_tail_fetch(conn):
    venue = FakeFundingVenue()
    w = "0xfresh"
    funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=DAY)
    funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=DAY + 60_000, fresh_s=900)
    assert len(venue.funding_calls) == 1
    funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=DAY + 3_600_000, fresh_s=900)
    assert len(venue.funding_calls) == 2


def test_persists_across_connections(tmp_path):
    venue = FakeFundingVenue()
    w = "0xpersist"
    venue.set_funding(w, [frow(1_000)])
    path = tmp_path / "persist.db"
    funding_cache.sync_funding(db.connect(path), venue, w, window_days=1, now_ms=10_000)
    import sqlite3
    c2 = sqlite3.connect(str(path))
    assert c2.execute("SELECT last_ms FROM funding_coverage WHERE wallet = ?", (w,)).fetchone()[0] == 10_000
    assert c2.execute("SELECT COUNT(*) FROM funding_v2 WHERE wallet = ?", (w,)).fetchone()[0] == 1


def test_same_coin_same_ms_dedupes_on_overlapping_fetch(conn):
    """insert_funding's (wallet, time_ms, coin) key dedupes an overlapping
    refetch: HL settles each coin's funding at most once per tick."""
    venue = FakeFundingVenue()
    w = "0xdedupe"
    venue.set_funding(w, [frow(1_000, coin="BTC"), frow(1_000, coin="ETH")])
    funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=2_000)
    funding_cache.sync_funding(conn, venue, w, window_days=1, now_ms=2_000, fresh_s=0)
    assert db.get_cached_funding(conn, w, 0, 2_000) == [
        {"time_ms": 1_000, "coin": "BTC", "usdc": -0.5, "funding_rate": 0.0000125},
        {"time_ms": 1_000, "coin": "ETH", "usdc": -0.5, "funding_rate": 0.0000125},
    ]
