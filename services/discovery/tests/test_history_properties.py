"""Property-based tests for the Trade history correctness checklist
(docs/research/user_consensus_2026-10.md). Each property holds for ANY
sequence of fills, not just the hand-picked fixtures in test_scout_metrics.py
and test_positions.py: these are the "laws" the checklist states as always
true, so hypothesis searches for a counter-example instead of us hand-writing
one more case.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from discovery import positions as P
from discovery.scout import metrics as M
from hypothesis import given, settings
from hypothesis import strategies as st

COIN = "BTC"
T0 = 1_700_000_000_000


def _fill(t: int, coin: str, side: str, sz: float, start: float, dir_: str = "") -> Dict[str, Any]:
    return {"time_ms": t, "coin": coin, "px": 100.0, "sz": sz, "side": side, "dir": dir_,
            "start_position": start, "fee": 0.0, "closed_pnl": 0.0}


@st.composite
def fill_walk(draw, max_steps: int = 14, force_flat: bool = False) -> List[Dict[str, Any]]:
    """A chronological sequence of fills for one coin, built by chaining
    start_position -> start_position + signed delta exactly the way a real
    fills cache does: every fill's `start_position` is the running position
    before it, so `positions.reconstruct` always sees a physically
    consistent walk (never two events claiming the account was flat at the
    same instant)."""
    steps = draw(st.integers(min_value=1, max_value=max_steps))
    deltas = draw(st.lists(st.sampled_from([d for d in range(-9, 10) if d != 0]), min_size=steps, max_size=steps))
    pos = 0.0
    t = T0
    fills: List[Dict[str, Any]] = []
    for d in deltas:
        side = "B" if d > 0 else "A"
        fills.append(_fill(t, COIN, side, float(abs(d)), pos))
        pos += d
        t += 1_000
    if force_flat and pos != 0:
        side = "A" if pos > 0 else "B"
        fills.append(_fill(t, COIN, side, abs(pos), pos))
        pos = 0.0
    return fills


@given(fill_walk())
@settings(max_examples=300)
def test_round_trips_count_equals_reconstructed_closes_law(fills: List[Dict[str, Any]]) -> None:
    """Round trips checklist, laws #1 and #2 together: a flip is a close
    plus a separate open (never one trip), and partial fills/adds/scale-outs
    aggregate into one trip. Both reduce to one countable fact: the number
    of trips `round_trips()` emits always equals the number of "close"
    events `positions.reconstruct` finds -- never more (no trip is split by
    aggregation), never fewer (no flip is merged into one trip)."""
    events = P.reconstruct(fills).get(COIN, [])
    expected = sum(1 for e in events if e.kind == "close")
    trips = M.round_trips(fills)
    assert len(trips) == expected
    assert all(t.opened_ms <= t.closed_ms for t in trips)
    assert trips == sorted(trips, key=lambda t: (t.closed_ms, t.coin))


@given(fill_walk(force_flat=False))
@settings(max_examples=300)
def test_a_trip_still_open_at_the_end_is_never_fabricated_law(fills: List[Dict[str, Any]]) -> None:
    """Checklist: trips still open at the window end are excluded from
    hold-time and win-rate stats, never counted as a win. round_trips()
    only ever emits a RoundTrip on a "close" event, so a walk that ends
    non-flat contributes no trailing trip for its final, still-open leg --
    checked here by confirming the trip count still matches the closes
    count (law #1) even when the walk is allowed to end open."""
    events = P.reconstruct(fills).get(COIN, [])
    still_open = events and events[-1].kind != "close"
    expected = sum(1 for e in events if e.kind == "close")
    trips = M.round_trips(fills)
    assert len(trips) == expected
    if still_open:
        last_open_ms = next(e.time_ms for e in reversed(events) if e.kind in ("open", "add"))
        assert all(t.closed_ms <= last_open_ms for t in trips) or not trips


@given(fill_walk(force_flat=True))
@settings(max_examples=200)
def test_liquidation_lands_on_the_trip_it_actually_closed_law(fills: List[Dict[str, Any]]) -> None:
    """Checklist: a liquidation is its own event type in the history, never
    folded into an ordinary closed loss. Flagging the fill that brings the
    coin flat (any walk here ends flat) as HL's own "Liquidated ..." dir
    must mark exactly the trip it closed, win or lose, and no other trip."""
    fills[-1] = dict(fills[-1], dir="Liquidated Isolated Long")
    trips = M.round_trips(fills)
    assert trips, "force_flat=True always produces at least one closed trip"
    closing_trip = trips[-1]
    assert closing_trip.closed_ms == fills[-1]["time_ms"]
    assert closing_trip.liquidation is True
    assert all(not t.liquidation for t in trips[:-1])


def test_duplicate_open_mid_trip_never_discards_the_real_fills_or_fabricates_a_second_trip() -> None:
    """Regression, measured 2026-10-14 reconciling a real whale wallet's
    cached fills (wallet 0x5d90...ff50, coin XPL): two overlapping
    incremental fills-cache syncs left the SAME opening batch cached twice
    under different primary keys -- 85 granular partial fills (0 -> 2,396,826)
    AND one single consolidated row claiming start_position=0 again at the
    identical ms, both for the same real economic open. A second "open"
    while a trip is already in progress is never a real position event (you
    cannot open what is already open): the old code unconditionally
    overwrote the in-progress trip's accumulator, silently discarding every
    fee and pnl already accumulated in the 85 granular fills. The fix
    (metrics.py round_trips, thesis/trips.py build_trips): drop the
    duplicate, keep the real trip's state."""
    real_open = _fill(T0, COIN, "B", 10.0, 0.0)              # the genuine granular open
    real_add = _fill(T0, COIN, "B", 5.0, 10.0)                # continues the same batch, 10 -> 15
    duplicate_open = dict(_fill(T0, COIN, "B", 15.0, 0.0), fee=999.0)   # the artifact: claims start=0 again
    real_close = _fill(T0 + 3_600_000, COIN, "A", 15.0, 15.0, dir_="Liquidated Isolated Long")
    fills = [dict(real_open, fee=1.0, closed_pnl=0.0), dict(real_add, fee=2.0, closed_pnl=0.0),
             duplicate_open, dict(real_close, fee=3.0, closed_pnl=-500.0)]

    trips = M.round_trips(fills)
    assert len(trips) == 1, "the duplicate open must never fabricate a second trip"
    t = trips[0]
    # the real fees (1 + 2 + 3 = 6) survive; the duplicate's bogus fee=999 never lands
    assert t.fee_usd == pytest.approx(6.0)
    assert t.gross_pnl_usd == pytest.approx(-500.0)
    assert t.liquidation is True
    assert t.entry_px == pytest.approx((10 * 100.0 + 5 * 100.0) / 15)  # the real adds, not the duplicate's
