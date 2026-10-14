"""Exports 5 real-wallet fixtures for the Trade history correctness checklist
(docs/research/user_consensus_2026-10.md) from the live Scout cache, read-only:

    sqlite3 "file:$HOME/Documents/code/copycat/data/discovery.db?mode=ro"

Addresses are public on-chain data (Hyperliquid), kept real so an eval can
re-read HL for the same wallet later. Never writes to the live db (opened
with `mode=ro`; also never the live checkout's path from an agent worktree).

How each wallet/coin/time-range was chosen (full methodology, so this is
re-derivable, not just re-runnable):

  1. flip -- scanned `fills_v2` for wallets with 100-3,000 total fills (small
     enough to review by eye), ran `discovery.positions.reconstruct` on each,
     and looked for a "close" immediately followed by an "open" at the exact
     same `time_ms` (one HL fill crossing zero), THEN filtered to cases where
     both the opening trip and the closing trip are fully inside the cached
     window (no "began before our first fill" drop). Wallet 0x057e...13220's
     ZEC history (only 3 fills total) is exactly that: open short -1.76,
     ONE fill flips it to long +1.76 (HL's own `dir` says only "Close
     Short" here -- understating what the size actually did; this is the
     real case positions.py's module docstring calls out: classify from
     start_position + sz + side, never trust the label), then a final close.
  2. partial fills + scale-outs -- same scan, wallets with >= 2 adds AND >= 2
     reduces on one coin within one otherwise-ordinary trip. Picked
     0x01b5...47cc, coin XLM: open, many adds, one early reduce, a long run
     of reduces, more adds, final close -- a real multi-phase trip.
  3. a real liquidation fill -- `SELECT wallet, COUNT(*) FROM fills_v2 WHERE
     dir LIKE 'Liquidated%' GROUP BY wallet`. Only ONE wallet in this whole
     575-wallet cache has a genuine OWN liquidation (top-leaderboard wallets
     survive by definition): 0x5d90...ff50, coin XPL, ms 1790172796967,
     `dir="Liquidated Isolated Long"`, a full close (sz == start_position).
     Trimmed to the one trip that closes there (its last "open" in the prior
     30 days through the liquidation). This trip ALSO contains a real
     artifact worth keeping on purpose (see below).
  4. a funding-heavy multi-day hold -- scanned wallets with >= 1 funding_v2
     row and modest fill counts for a trip with hold_h >= 24 and
     |net funding| >= $5. Picked 0x0682...b571, coin HYPE: a clean single
     open-to-close trip, 170h hold, -$735.94 net funding (the trader was
     long while HYPE's funding rate was positive, so longs paid shorts --
     HL's sign convention, see contracts/venue.py Venue.funding).
  5. a truncated history -- `fills_truncated()`'s real law (>= 9,000 fills in
     the 30d window, oldest well after the window start) needs thousands of
     rows to trigger honestly; keeping all of them would blow the 200 KB cap
     for no benefit (the law itself is covered by a hypothesis/parametrized
     test, not a giant fixture). Picked 0x3bca...66f3 instead for its REAL
     shape: a live `fills_coverage` query (below) found a genuine 11-day gap
     then 21,402 fills crammed into the remaining ~19 days -- the fixture
     keeps the real coverage numbers (`meta`) plus a representative trimmed
     sample of the top two coins, not the whole 21k rows.

Re-run: `/Users/julian_dev/Documents/code/copycat/.venv/bin/python
services/discovery/tests/fixtures/history/make_fixtures.py` from the repo
root. Each file is printed with its byte size; the script asserts every file
stays under 200 KB.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB = "file:/Users/julian_dev/Documents/code/copycat/data/discovery.db?mode=ro"
OUT = Path(__file__).resolve().parent
MAX_BYTES = 200 * 1024
DAY_MS = 86_400_000

FILLS_SQL = (
    "SELECT time_ms, coin, px, sz, side, dir, start_position, closed_pnl, fee, liquidation "
    "FROM fills_v2 WHERE wallet = ? {coin_clause} AND time_ms BETWEEN ? AND ? ORDER BY time_ms"
)
FUNDING_SQL = (
    "SELECT time_ms, coin, usdc, funding_rate FROM funding_v2 "
    "WHERE wallet = ? {coin_clause} AND time_ms BETWEEN ? AND ? ORDER BY time_ms"
)


def _rows(conn: sqlite3.Connection, sql: str, coin: Optional[str], wallet: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    clause = "AND coin = ?" if coin else ""
    params = (wallet, coin, start_ms, end_ms) if coin else (wallet, start_ms, end_ms)
    rows = conn.execute(sql.format(coin_clause=clause), params).fetchall()
    return [dict(r) for r in rows]


def export(conn: sqlite3.Connection, name: str, scenario: str, query: str, wallet: str, coin: Optional[str],
          start_ms: int, end_ms: int, meta: Optional[Dict[str, Any]] = None) -> None:
    fills = _rows(conn, FILLS_SQL, coin, wallet, start_ms, end_ms)
    funding = _rows(conn, FUNDING_SQL, coin, wallet, start_ms, end_ms)
    for f in fills:
        f["liquidation"] = bool(f["liquidation"])
    body = {"scenario": scenario, "wallet": wallet, "coin": coin, "start_ms": start_ms, "end_ms": end_ms,
            "query": query, "fills": fills, "funding": funding}
    if meta:
        body["meta"] = meta
    path = OUT / f"{name}.json"
    text = json.dumps(body, indent=2)
    size = len(text.encode())
    assert size <= MAX_BYTES, f"{name}.json is {size} bytes, over the {MAX_BYTES} cap"
    path.write_text(text + "\n")
    print(f"wrote {path.relative_to(OUT.parents[3])} ({size:,} bytes, {len(fills)} fills, {len(funding)} funding rows)")


def main() -> None:
    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row

    export(
        conn, "flip", "a flip: short to long with no flat in between, one HL fill, both trips fully captured",
        "SELECT ... FROM fills_v2 WHERE wallet='0x057e...13220' AND coin='ZEC' ORDER BY time_ms",
        wallet="0x057e4ef25b051110f91102d71ae9fecb2e913220", coin="ZEC",
        start_ms=1_789_186_000_000, end_ms=1_790_612_000_000,
    )

    export(
        conn, "scale_out", "partial fills, adds and scale-outs aggregating into one trip",
        "SELECT ... FROM fills_v2 WHERE wallet='0x01b5...47cc' AND coin='XLM' ORDER BY time_ms",
        wallet="0x01b5dfdd91c2103bfb3c37cb64d32561895c47cc", coin="XLM",
        start_ms=1_790_613_000_000, end_ms=1_791_474_000_000,
    )

    export(
        conn, "liquidation", "a real HL liquidation (HL dir 'Liquidated Isolated Long'), own full close",
        "SELECT ... FROM fills_v2 WHERE wallet='0x5d90...ff50' AND coin='XPL' "
        "AND time_ms BETWEEN 1789996934478 AND 1790172796967 ORDER BY time_ms",
        wallet="0x5d908c88be270889c0953e7dff1c8e1d699ceea3", coin="XPL",
        start_ms=1_789_996_934_478, end_ms=1_790_172_796_967,
        meta={"note": "Contains a real fills-cache duplicate artifact at ms 1789996934478 (a second "
                      "'open' row claiming start_position=0 after the position was already built up "
                      "by the preceding granular fills, measured 2026-10-14): round_trips() and "
                      "build_trips() must drop it, not fabricate a second trip or discard the real "
                      "fees/pnl (see test_history_properties.py's duplicate-open regression)."}
    )

    export(
        conn, "funding_heavy", "a funding-heavy multi-day hold, net funding a meaningful share of PnL",
        "SELECT ... FROM fills_v2 WHERE wallet='0x0682...b571' AND coin='HYPE' "
        "AND time_ms BETWEEN 1790783181381 AND 1791395375743 ORDER BY time_ms",
        wallet="0x0682f4ee106d167ca46ed015918e83f6f4e5b571", coin="HYPE",
        start_ms=1_790_783_181_381, end_ms=1_791_395_375_743,
    )

    # Truncated history: real coverage numbers from the live db (fills_coverage.fetched_ms as
    # this wallet's "now"), a trimmed sample of its busiest coin for shape, not the full
    # 21,402-row window (fills_truncated()'s 9,000-row law itself gets a parametrized test, not
    # a giant fixture -- see services/discovery/tests/test_scout_metrics.py). This wallet trades
    # thousands of times a DAY, so even a 2-day slice is hundreds of KB; sampled by row count
    # (newest N) instead of a time range to hit the 200 KB cap.
    SAMPLE_ROWS = 400
    now_ms = conn.execute("SELECT fetched_ms FROM fills_coverage WHERE wallet = ?",
                          ("0x3bcae23e8c380dab4732e9a159c0456f12d866f3",)).fetchone()[0]
    ws30 = now_ms - 30 * DAY_MS
    wallet = "0x3bcae23e8c380dab4732e9a159c0456f12d866f3"
    total_30d = conn.execute("SELECT COUNT(*) FROM fills_v2 WHERE wallet = ? AND time_ms >= ?", (wallet, ws30)).fetchone()[0]
    oldest_30d = conn.execute("SELECT MIN(time_ms) FROM fills_v2 WHERE wallet = ? AND time_ms >= ?", (wallet, ws30)).fetchone()[0]
    sample_sql = ("SELECT time_ms, coin, px, sz, side, dir, start_position, closed_pnl, fee, liquidation "
                  "FROM fills_v2 WHERE wallet = ? ORDER BY time_ms DESC LIMIT ?")
    fills_sample = [dict(r) for r in conn.execute(sample_sql, (wallet, SAMPLE_ROWS)).fetchall()]
    for f in fills_sample:
        f["liquidation"] = bool(f["liquidation"])
    fills_sample.sort(key=lambda f: f["time_ms"])
    body = {
        "scenario": "a truncated history: HL serves only the newest ~10k fills, missing older ones",
        "wallet": wallet, "coin": None, "start_ms": fills_sample[0]["time_ms"], "end_ms": fills_sample[-1]["time_ms"],
        "query": f"SELECT ... FROM fills_v2 WHERE wallet=? ORDER BY time_ms DESC LIMIT {SAMPLE_ROWS} "
                 "-- newest-N shape sample (this wallet trades thousands of times/day); "
                 "see `meta` for the real 30d population this represents",
        "fills": fills_sample, "funding": [],
        "meta": {
            "now_ms": now_ms, "window_start_ms": ws30, "real_fills_30d_count": total_30d,
            "real_oldest_fill_ms_in_30d_window": oldest_30d,
            "real_gap_hours_at_window_start": round((oldest_30d - ws30) / 3_600_000, 1),
            "note": "real_gap_hours_at_window_start >> 24h: discovery.scout.metrics.fills_truncated "
                    "(fills, window_start_ms) is True on the real, untrimmed 30d population recorded "
                    "here (TRUNCATED_MIN_FILLS=9000, services/discovery/discovery/scout/config.py); "
                    "the eval (services/discovery/evals/history_check.sh) re-reads this wallet live "
                    "and checks the flag against fresh HL data, not this snapshot.",
        },
    }
    path = OUT / "truncated.json"
    text = json.dumps(body, indent=2)
    size = len(text.encode())
    assert size <= MAX_BYTES, f"truncated.json is {size} bytes, over the {MAX_BYTES} cap"
    path.write_text(text + "\n")
    print(f"wrote {path.relative_to(OUT.parents[3])} ({size:,} bytes, {len(body['fills'])} sample fills; "
          f"real 30d population: {total_30d:,} fills, gap {body['meta']['real_gap_hours_at_window_start']}h)")


if __name__ == "__main__":
    main()
