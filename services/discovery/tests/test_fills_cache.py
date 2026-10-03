from __future__ import annotations

from discovery import db, fills_cache

from discovery_fakes import FakeVenue


def fill(time_ms, coin="BTC", px=100.0, sz=1.0, side="B", start_position=0.0):
    return {"time_ms": time_ms, "coin": coin, "px": px, "sz": sz, "side": side,
            "start_position": start_position, "fee": 0.0, "closed_pnl": 0.0}


def test_sync_fills_only_fetches_since_last_cursor(conn):
    venue = FakeVenue()
    wallet = "0xabc"
    venue.set_fills(wallet, [fill(14_000_000), fill(50_000_000)])

    out1 = fills_cache.sync_fills(conn, venue, wallet, window_days=1, now_ms=100_000_000)
    assert {f["time_ms"] for f in out1} == {14_000_000, 50_000_000}
    assert venue.fills_calls == [(wallet, 13_600_000, 100_000_000)]
    assert db.get_fills_cursor(conn, wallet) == 100_000_000

    # a fresh fill shows up after the cursor; an old one re-added to the fixture must not be re-fetched
    venue.set_fills(wallet, [fill(14_000_000), fill(50_000_000), fill(100_200_000)])
    out2 = fills_cache.sync_fills(conn, venue, wallet, window_days=1, now_ms=100_500_000)

    assert venue.fills_calls[1] == (wallet, 100_000_001, 100_500_000)  # only the gap, never re-fetched
    assert 100_200_000 in {f["time_ms"] for f in out2}
    assert 14_000_000 not in {f["time_ms"] for f in out2}  # slid out of the (now later) 1-day window


def test_sync_fills_empty_wallet_returns_empty_list(conn):
    venue = FakeVenue()
    out = fills_cache.sync_fills(conn, venue, "0xnobody", window_days=30, now_ms=1_000_000)
    assert out == []


def test_sync_fills_persists_across_separate_db_connections(tmp_path):
    venue = FakeVenue()
    wallet = "0xpersist"
    venue.set_fills(wallet, [fill(1_000)])
    db_path = tmp_path / "persist.db"

    conn1 = db.connect(db_path)
    fills_cache.sync_fills(conn1, venue, wallet, window_days=1, now_ms=10_000)

    # a brand new connection to the same file sees the cursor and the cached fill
    import sqlite3
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    cursor_row = conn2.execute("SELECT last_ms FROM fills_cursor WHERE wallet = ?", (wallet,)).fetchone()
    assert cursor_row["last_ms"] == 10_000
    fill_rows = conn2.execute("SELECT * FROM fills WHERE wallet = ?", (wallet,)).fetchall()
    assert len(fill_rows) == 1
