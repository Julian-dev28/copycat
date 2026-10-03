"""Reconstruct a leader's per-coin position deltas from raw fills.

Per the task spec: classification comes from arithmetic on start_position +
sz + side, not from HL's own `dir` label string. This is deliberate --
`dir` is HL's own classification and isn't guaranteed to be populated the
same way by every source (and our synthetic test fixtures shouldn't need to
fabricate it correctly). side is "B" (buy) or "A" (sell/ask); sz is an
unsigned magnitude.

A fill's sign change (start_position and end_position straddle zero) is a
flip: closing the old side and opening the new one in a single fill. We
model that as two separate events (a close of the old side immediately
followed by an open of the new side, both at the fill's price and
timestamp) because the copier's book has to do exactly that -- you cannot
"flip" a position at a different venue/account in one atomic order; you
close what you have and open the other side. This is a documented sim
simplification (see README): real HL flip fills cross zero in one
exchange-side trade, our copy executes it as two.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

Kind = Literal["open", "add", "reduce", "close"]
Side = Literal["long", "short"]


@dataclass
class PositionEvent:
    coin: str
    time_ms: int
    kind: Kind
    side: Side          # side of the position being opened/added-to/reduced/closed
    delta_sz: float      # unsigned magnitude of the size change
    start_position: float
    end_position: float
    px: float            # leader's fill price
    fee: float = 0.0
    closed_pnl: float = 0.0


def _side_of(signed: float) -> Side:
    return "long" if signed > 0 else "short"


def _classify_one(coin: str, time_ms: int, start: float, end: float, px: float,
                   fee: float, closed_pnl: float) -> List[PositionEvent]:
    if start == 0 and end == 0:
        return []
    if start == 0:
        return [PositionEvent(coin, time_ms, "open", _side_of(end), abs(end), start, end, px, fee, closed_pnl)]
    if end == 0:
        return [PositionEvent(coin, time_ms, "close", _side_of(start), abs(start), start, end, px, fee, closed_pnl)]
    same_side = (start > 0) == (end > 0)
    if same_side:
        kind: Kind = "add" if abs(end) > abs(start) else "reduce"
        return [PositionEvent(coin, time_ms, kind, _side_of(start), abs(abs(end) - abs(start)),
                               start, end, px, fee, closed_pnl)]
    # flip: close the old side entirely, then open the new side entirely.
    close_evt = PositionEvent(coin, time_ms, "close", _side_of(start), abs(start), start, 0.0,
                               px, fee, closed_pnl)
    open_evt = PositionEvent(coin, time_ms, "open", _side_of(end), abs(end), 0.0, end, px, 0.0, 0.0)
    return [close_evt, open_evt]


def reconstruct(fills: List[Dict[str, Any]]) -> Dict[str, List[PositionEvent]]:
    """fills: chronological (any coin mix), each with time_ms/coin/px/sz/side/
    start_position/fee/closed_pnl. Returns coin -> chronological PositionEvent
    list."""
    by_coin: Dict[str, List[PositionEvent]] = {}
    for f in sorted(fills, key=lambda r: r["time_ms"]):
        side = f["side"]
        delta = abs(float(f["sz"])) * (1.0 if side == "B" else -1.0)
        start = float(f["start_position"])
        end = start + delta
        events = _classify_one(f["coin"], int(f["time_ms"]), start, end, float(f["px"]),
                                float(f.get("fee", 0.0)), float(f.get("closed_pnl", 0.0)))
        if events:
            by_coin.setdefault(f["coin"], []).extend(events)
    return by_coin


def merged_timeline(by_coin: Dict[str, List[PositionEvent]]) -> List[PositionEvent]:
    """All coins' events merged into one chronological replay order (stable
    sort: ties keep coin-group relative order, deterministic)."""
    all_events = [e for events in by_coin.values() for e in events]
    all_events.sort(key=lambda e: e.time_ms)
    return all_events


# ── stats derived from the reconstructed timeline ──────────────────────────

def opens_per_day(by_coin: Dict[str, List[PositionEvent]], window_days: int) -> float:
    n_opens = sum(1 for events in by_coin.values() for e in events if e.kind == "open")
    return round(n_opens / window_days, 3) if window_days > 0 else 0.0


def median_hold_hours(by_coin: Dict[str, List[PositionEvent]]) -> Tuple[Optional[float], int]:
    """Median hold time for trips that open AND close within the fetched
    window. A trip open before the window or still open at fetch time is
    excluded by construction -- this undercounts, never fabricates."""
    durations: List[float] = []
    for events in by_coin.values():
        open_t: Optional[int] = None
        for e in events:
            if e.kind == "open":
                open_t = e.time_ms
            elif e.kind == "close" and open_t is not None:
                durations.append((e.time_ms - open_t) / 3_600_000)
                open_t = None
    if not durations:
        return None, 0
    return statistics.median(durations), len(durations)


def coins_traded(by_coin: Dict[str, List[PositionEvent]]) -> List[str]:
    return sorted(by_coin.keys())
