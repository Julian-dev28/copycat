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


def test_liquidation_flag_round_trips_through_the_cache(conn):
    """HL's own liquidation flag (hl.venue.fills) must survive the cache,
    not just the in-memory fill dict (regression: it was fetched and then
    dropped before insert_fills)."""
    venue = FakeVenue()
    w = "0xliq"
    f = fill(1_000)
    f["liquidation"] = True
    venue.set_fills(w, [f])
    out = fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=10_000)
    assert bool(out[0]["liquidation"]) is True   # sqlite stores it as an INTEGER, not a Python bool


def test_liquidation_column_migrates_onto_a_pre_existing_fills_v2_table(tmp_path):
    """A real data/discovery.db predates this column: connect() must add it
    (ALTER TABLE, not a fresh CREATE) and insert_fills/get_cached_fills must
    keep working against that migrated table."""
    import sqlite3

    path = tmp_path / "old_schema.db"
    pre = sqlite3.connect(str(path))
    pre.execute("""
        CREATE TABLE fills_v2 (
            wallet TEXT NOT NULL, time_ms INTEGER NOT NULL, coin TEXT NOT NULL, px REAL NOT NULL,
            sz REAL NOT NULL, side TEXT NOT NULL, dir TEXT, start_position REAL NOT NULL,
            closed_pnl REAL NOT NULL DEFAULT 0, fee REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (wallet, time_ms, coin, side, sz, px, start_position)
        )""")
    pre.execute("INSERT INTO fills_v2 (wallet, time_ms, coin, px, sz, side, dir, start_position) "
                "VALUES ('0xold', 500, 'BTC', 100.0, 1.0, 'B', 'Open Long', 0.0)")
    pre.commit()
    pre.close()

    conn = db.connect(path)
    pre_existing = db.get_cached_fills(conn, "0xold", 0, 1000)
    assert pre_existing[0]["liquidation"] == 0   # migrated column defaults to 0, not NULL/missing

    db.insert_fills(conn, "0xnew", [fill(600, coin="ETH")])
    f = fill(700, coin="SOL")
    f["liquidation"] = True
    db.insert_fills(conn, "0xnew", [f])
    rows = {r["coin"]: r["liquidation"] for r in db.get_cached_fills(conn, "0xnew", 0, 1000)}
    assert rows == {"ETH": 0, "SOL": 1}


# ── liquidation backfill (coordinator follow-up: fills cached before the ──
# ── `liquidation` column existed stay 0 forever without this) ────────────

def test_a_brand_new_wallet_is_marked_backfilled_on_its_first_sync(conn):
    """A wallet synced for the first time after this column shipped already
    has the real flag on every cached row: no refetch is ever needed for it."""
    venue = FakeVenue()
    w = "0xbrandnew"
    venue.set_fills(w, [fill(1_000)])
    fills_cache.sync_fills(conn, venue, w, window_days=1, now_ms=10_000)
    assert db.get_fills_coverage(conn, w)["liq_backfilled"] == 1
    assert fills_cache.ensure_liquidation_backfilled(conn, venue, w) is False
    assert len(venue.fills_calls) == 1   # only the one sync call, no extra refetch


def test_ensure_liquidation_backfilled_corrects_a_pre_migration_zero(conn):
    """The exact scenario this exists for: a fill cached before the
    `liquidation` column existed has it hard-0 regardless of HL's real
    value. One profile build must correct it from HL; a second must not
    refetch at all."""
    venue = FakeVenue()
    w = "0xpremigration"
    # Simulate data written before the column existed: insert_fills + set_fills_coverage
    # directly (not sync_fills), as a real pre-migration discovery.db would already have it,
    # with liq_backfilled left at its column default (0).
    db.insert_fills(conn, w, [fill(1_000)])             # liquidation defaults to 0
    db.set_fills_coverage(conn, w, 0, 10_000, 10_000)
    assert db.get_fills_coverage(conn, w)["liq_backfilled"] == 0

    f = fill(1_000)
    f["liquidation"] = True                              # HL's real answer: this WAS a liquidation
    venue.set_fills(w, [f])

    assert fills_cache.ensure_liquidation_backfilled(conn, venue, w) is True
    assert venue.fills_calls == [(w, 0, 10_000)]
    row = db.get_cached_fills(conn, w, 0, 10_000)[0]
    assert bool(row["liquidation"]) is True
    assert db.get_fills_coverage(conn, w)["liq_backfilled"] == 1

    # second call: already done, must not refetch
    assert fills_cache.ensure_liquidation_backfilled(conn, venue, w) is False
    assert venue.fills_calls == [(w, 0, 10_000)]          # unchanged


def test_ensure_liquidation_backfilled_is_a_no_op_with_no_cached_fills(conn):
    venue = FakeVenue()
    assert fills_cache.ensure_liquidation_backfilled(conn, venue, "0xnever-synced") is False
    assert venue.fills_calls == []


def test_ensure_liquidation_backfilled_retries_on_a_failed_read(conn):
    venue = FakeVenue()
    w = "0xflaky"
    db.insert_fills(conn, w, [fill(1_000)])
    db.set_fills_coverage(conn, w, 0, 10_000, 10_000)
    venue.fail_fills.add(w)

    assert fills_cache.ensure_liquidation_backfilled(conn, venue, w) is False
    assert db.get_fills_coverage(conn, w)["liq_backfilled"] == 0   # not marked done: must retry

    venue.fail_fills.clear()
    venue.set_fills(w, [fill(1_000)])
    assert fills_cache.ensure_liquidation_backfilled(conn, venue, w) is True
    assert db.get_fills_coverage(conn, w)["liq_backfilled"] == 1
