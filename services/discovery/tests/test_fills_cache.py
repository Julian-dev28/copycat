from __future__ import annotations

import pytest
from discovery import db, fills_cache
from discovery_fakes import FakeVenue

DAY = 86_400_000


def fill(time_ms, coin="BTC", px=100.0, sz=1.0, side="B", start_position=0.0):
    return {"time_ms": time_ms, "coin": coin, "px": px, "sz": sz, "side": side,
            "start_position": start_position, "fee": 0.0, "closed_pnl": 0.0}


def test_only_fetches_outside_coverage(conn):
    venue = FakeVenue()
    w = "0xabc"
    venue.set_fills(w, [fill(14_000_000), fill(50_000_000)])
    out1 = fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=100_000_000)
    assert {f["time_ms"] for f in out1} == {14_000_000, 50_000_000}
    assert venue.fills_calls == [(w, 13_600_000, 100_000_000)]

    venue.set_fills(w, [fill(14_000_000), fill(50_000_000), fill(100_200_000)])
    out2 = fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=100_500_000)
    assert venue.fills_calls[1] == (w, 100_000_001, 100_500_000)
    assert 100_200_000 in {f["time_ms"] for f in out2}
    assert 14_000_000 not in {f["time_ms"] for f in out2}


def test_wider_window_backfills_only_the_older_part(conn):
    venue = FakeVenue()
    w = "0xwide"
    now = 10 * DAY
    venue.set_fills(w, [fill(2 * DAY), fill(9 * DAY)])
    fills_cache.sync_fills(conn, venue, w, window_days=3, now_ms=now)
    out = fills_cache.sync_fills(conn, venue, w, window_days=9, now_ms=now)
    assert venue.fills_calls[1] == (w, 1 * DAY, 7 * DAY - 1)
    assert len(venue.fills_calls) == 2               # no tail fetch: coverage already reaches now
    assert {f["time_ms"] for f in out} == {2 * DAY, 9 * DAY}


def test_failed_read_raises_and_leaves_coverage_untouched(conn):
    """Regression: a 429 used to return None, the loop broke, and the cursor
    still moved to now: the wallet then looked flat forever."""
    venue = FakeVenue()
    w = "0xrate"
    venue.set_fills(w, [fill(5_000)])
    venue.fail_fills.add(w)
    with pytest.raises(fills_cache.FillsFetchError):
        fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=10_000)
    assert db.get_fills_coverage(conn, w) is None
    venue.fail_fills.clear()
    assert len(fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=10_000)) == 1


def test_fresh_coverage_skips_the_tail_fetch(conn):
    venue = FakeVenue()
    w = "0xfresh"
    fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=DAY)
    fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=DAY + 60_000, fresh_s=900)
    assert len(venue.fills_calls) == 1
    fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=DAY + 3_600_000, fresh_s=900)
    assert len(venue.fills_calls) == 2


def test_passes_aggregate_by_time_when_the_venue_supports_it(conn):
    seen = []

    class AggVenue(FakeVenue):
        def fills(self, user, start_ms, end_ms, aggregate_by_time=False):
            seen.append(aggregate_by_time)
            return []

    fills_cache.sync_fills(conn, AggVenue(), "0xagg", window_days=1, now_ms=DAY)
    assert seen == [True]


def test_persists_across_connections(tmp_path):
    venue = FakeVenue()
    w = "0xpersist"
    venue.set_fills(w, [fill(1_000)])
    path = tmp_path / "persist.db"
    fills_cache.sync_fills(db.connect(path), venue, w, window_days=1, now_ms=10_000)
    import sqlite3
    c2 = sqlite3.connect(str(path))
    assert c2.execute("SELECT last_ms FROM fills_coverage WHERE wallet = ?", (w,)).fetchone()[0] == 10_000
    assert c2.execute("SELECT COUNT(*) FROM fills_v2 WHERE wallet = ?", (w,)).fetchone()[0] == 1


def test_identical_twap_fills_at_the_same_ms_are_all_kept(conn):
    """Regression: the v1 key (wallet, ms, coin, side, sz, px) collapsed a
    TWAP leader's identical same-ms slices into one fill."""
    venue = FakeVenue()
    w = "0xtwap"
    venue.set_fills(w, [fill(1_000, sz=1.0, start_position=0.0), fill(1_000, sz=1.0, start_position=1.0),
                        fill(1_000, sz=1.0, start_position=2.0)])
    assert len(fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=10_000)) == 3
