"""Real-wallet fixtures (services/discovery/tests/fixtures/history/*.json,
made by that directory's make_fixtures.py from the live Scout cache) proving
every Trade history correctness checklist line against real Hyperliquid
shapes, not just hand-built cases. Addresses are public on-chain data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from discovery import positions as P
from discovery.scout import config as C
from discovery.scout import metrics as M
from discovery.thesis.trips import build_trips

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "history"


def load(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_flip_fixture_splits_into_a_close_and_a_separate_open():
    """Real wallet 0x057e...13220, coin ZEC, 3 fills total: open short
    -1.76, ONE fill flips it to long +1.76 (HL's own `dir` understates this
    as "Close Short" -- classification must come from the arithmetic, not
    the label, positions.py's module docstring), then a final close. Both
    trips are fully inside the fetched window: nothing dropped as
    "began before our first fill"."""
    d = load("flip")
    trips = M.round_trips(d["fills"])
    assert len(trips) == 2
    short, long_ = trips
    assert short.side == "short" and long_.side == "long"
    assert short.coin == long_.coin == "ZEC"
    # the flip: the long's open is the exact instant the short's close is
    assert short.closed_ms == long_.opened_ms
    assert short.net_pnl_usd == pytest.approx(short.gross_pnl_usd - short.fee_usd)
    assert long_.net_pnl_usd == pytest.approx(long_.gross_pnl_usd - long_.fee_usd)
    assert not short.win and long_.win   # -630.23 on the flip's close leg, +33.56 on the new long


def test_scale_out_fixture_aggregates_partial_fills_and_scale_outs_into_one_trip():
    """Real wallet 0x01b5...47cc, coin XLM: open, dozens of adds, an early
    reduce, a long run of reduces, more adds, final close -- 95 raw fills,
    one trip. build_trips (thesis) counts >= 2 add actions and >= 2 exit
    actions, proving the aggregation is real scaling, not a fluke."""
    d = load("scale_out")
    fills = d["fills"]
    trips = M.round_trips(fills)
    assert len(trips) == 1
    t = trips[0]
    assert t.coin == "XLM"
    assert t.gross_pnl_usd == pytest.approx(sum(f["closed_pnl"] for f in fills))
    assert t.fee_usd == pytest.approx(sum(f["fee"] for f in fills))
    assert t.net_pnl_usd == pytest.approx(t.gross_pnl_usd - t.fee_usd)

    thesis_trips, still_open = build_trips(fills)
    assert still_open == 0 and len(thesis_trips) == 1
    assert thesis_trips[0].adds >= 2
    assert thesis_trips[0].exits >= 2   # the close included


def test_liquidation_fixture_is_its_own_event_type_and_keeps_the_real_fees():
    """Real wallet 0x5d90...ff50, coin XPL: the only genuine OWN liquidation
    (HL dir "Liquidated Isolated Long") in this 575-wallet cache, AND a real
    fills-cache artifact (a duplicate consolidated "open" row mid-batch,
    see make_fixtures.py's docstring). round_trips() must mark the trip
    liquidated, count it as exactly one trip, and keep the real fees/pnl --
    the duplicate (identified here the same way it is real: the one fill,
    other than the chronological first, that claims start_position == 0)
    contributes nothing."""
    d = load("liquidation")
    fills = d["fills"]
    dup_idx = [i for i, f in enumerate(fills) if i > 0 and f["start_position"] == 0.0]
    assert len(dup_idx) == 1, "expected exactly the one known duplicate-open artifact"
    real = [f for i, f in enumerate(fills) if i != dup_idx[0]]

    trips = M.round_trips(fills)
    assert len(trips) == 1
    t = trips[0]
    assert t.liquidation is True
    assert t.fee_usd == pytest.approx(sum(f["fee"] for f in real), abs=1e-6)
    assert t.gross_pnl_usd == pytest.approx(sum(f["closed_pnl"] for f in real), abs=1e-6)

    liq_count, liq_last_ms = M.real_liquidations(fills)
    assert liq_count == 1 and liq_last_ms == d["end_ms"]


def test_funding_heavy_fixture_nets_meaningful_funding_into_the_trip():
    """Real wallet 0x0682...b571, coin HYPE: a clean 170h open-to-close
    hold. The trader was long while HYPE's funding rate stayed positive
    (HL's own convention, contracts/venue.py: longs pay shorts), so net
    funding is negative and large enough to flip the read on the trip
    without it (gross alone reads as a solid win; funding takes a real
    bite). Recorded once from this exact fixture: -735.94 (computed
    2026-10-14 via discovery.positions.funding_by_trip on the real rows)."""
    d = load("funding_heavy")
    trips = M.round_trips(d["fills"], d["funding"])
    assert len(trips) == 1
    t = trips[0]
    assert t.side == "long" and t.hold_h == pytest.approx(170.05, abs=0.01)
    assert t.gross_pnl_usd > 0   # a real win before funding
    assert t.funding_usd == pytest.approx(-735.94, abs=0.5)
    assert t.net_pnl_usd == pytest.approx(t.gross_pnl_usd - t.fee_usd + t.funding_usd)
    # funding alone (~17% of gross here) outweighs the fee by nearly 2x: material enough that
    # netting fees but not funding, as the checklist's P0 originally flagged, would still mislead
    assert abs(t.funding_usd) > t.gross_pnl_usd * 0.15
    assert abs(t.funding_usd) > t.fee_usd * 1.5


def test_truncated_fixture_flags_real_against_the_recorded_live_population():
    """Real wallet 0x3bca...66f3: fills_truncated()'s law (>= 9,000 fills in
    the 30d window, oldest well after the window start) needs thousands of
    rows to trigger honestly, so the fixture keeps the real recorded
    population counts (`meta`, from the live db) instead of checking in all
    21,402 rows. Builds a same-shaped synthetic population at the REAL
    recorded count/gap and checks the real law against it; separately smoke-
    tests that the trimmed 400-row sample (real shapes) parses cleanly."""
    d = load("truncated")
    meta = d["meta"]
    assert meta["real_fills_30d_count"] >= C.TRUNCATED_MIN_FILLS
    assert meta["real_gap_hours_at_window_start"] > 24

    synthetic = [{"time_ms": meta["real_oldest_fill_ms_in_30d_window"] + i}
                for i in range(meta["real_fills_30d_count"])]
    assert M.fills_truncated(synthetic, meta["window_start_ms"]) is True
    # a population with the gap but under the count law is not truncated
    assert M.fills_truncated(synthetic[:100], meta["window_start_ms"]) is False

    # the trimmed real sample still parses: no exception, a sane trip/fill count
    fills = d["fills"]
    perp, other = P.split_perp(fills)
    assert not other   # BTC/ETH are perp coins, nothing filtered out
    trips = M.round_trips(fills)
    assert isinstance(trips, list)
    liq_count, _ = M.real_liquidations(fills)
    assert liq_count >= 0
