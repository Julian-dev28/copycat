"""Round trips with the sizing detail the fingerprint needs (adds, exits).

Built on positions.reconstruct, so classification is arithmetic on
start_position + signed size and a flip is a close then an open. Same
trip rules as scout.metrics.round_trips: a trip already open at the first
fill we have is dropped (never fabricated), one still open at the last
fill is counted in `open_count` and left out of every metric.

Actions: fills on the same side of the book within ACTION_MERGE_MS of the
previous one are one action. A TWAP or a market order that crossed
several resting orders is one add (or one exit), not forty.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from contracts.models import RoundTrip

from .. import positions
from . import config as C


@dataclass(frozen=True)
class Trip:
    coin: str
    side: str                 # "long" | "short"
    opened_ms: int
    closed_ms: int
    open_px: float            # first fill's price: the entry the context is measured at
    entry_px: float           # size-weighted average of opens/adds
    exit_px: float            # size-weighted average of reduces/close
    max_notional_usd: float
    net_pnl_usd: float        # sum(closed_pnl) - sum(fee)
    adds: int                 # entry actions after the open
    exits: int                # exit actions, the close included (>= 1)

    @property
    def hold_h(self) -> float:
        return (self.closed_ms - self.opened_ms) / C.HOUR_MS

    @property
    def return_pct(self) -> float:
        return self.net_pnl_usd / self.max_notional_usd * 100.0 if self.max_notional_usd > 0 else 0.0

    @property
    def key(self) -> Tuple[int, str, str]:
        return (self.opened_ms, self.coin, self.side)

    def to_round_trip(self) -> RoundTrip:
        return RoundTrip(coin=self.coin, side=self.side, opened_ms=self.opened_ms, closed_ms=self.closed_ms,
                         hold_h=round(self.hold_h, 6), entry_px=self.entry_px, exit_px=self.exit_px,
                         max_notional_usd=round(self.max_notional_usd, 2),
                         net_pnl_usd=round(self.net_pnl_usd, 6), win=self.net_pnl_usd > 0)


def build_trips(fills: Sequence[Dict[str, Any]]) -> Tuple[List[Trip], int]:
    """(closed trips sorted by (opened_ms, coin), number of trips still open)."""
    perp, _ = positions.split_perp(list(fills))
    trips: List[Trip] = []
    still_open = 0
    for coin, events in positions.reconstruct(perp).items():
        cur: Optional[Dict[str, Any]] = None
        for e in events:
            if e.kind == "open":
                cur = {"side": e.side, "opened": e.time_ms, "open_px": e.px,
                       "in_sz": e.delta_sz, "in_ntl": e.delta_sz * e.px, "out_sz": 0.0, "out_ntl": 0.0,
                       "pnl": e.closed_pnl, "fee": e.fee, "max_ntl": abs(e.end_position) * e.px,
                       "adds": 0, "exits": 0, "last_in": e.time_ms, "last_out": None}
                continue
            if cur is None:
                continue                      # trip began before our first fill
            cur["pnl"] += e.closed_pnl
            cur["fee"] += e.fee
            if e.kind == "add":
                cur["in_sz"] += e.delta_sz
                cur["in_ntl"] += e.delta_sz * e.px
                if e.time_ms - cur["last_in"] > C.ACTION_MERGE_MS:
                    cur["adds"] += 1
                cur["last_in"] = e.time_ms
            else:
                cur["out_sz"] += e.delta_sz
                cur["out_ntl"] += e.delta_sz * e.px
                if cur["last_out"] is None or e.time_ms - cur["last_out"] > C.ACTION_MERGE_MS:
                    cur["exits"] += 1
                cur["last_out"] = e.time_ms
            cur["max_ntl"] = max(cur["max_ntl"], abs(e.end_position) * e.px, abs(e.start_position) * e.px)
            if e.kind == "close":
                trips.append(Trip(
                    coin=coin, side=cur["side"], opened_ms=cur["opened"], closed_ms=e.time_ms,
                    open_px=cur["open_px"],
                    entry_px=cur["in_ntl"] / cur["in_sz"] if cur["in_sz"] else e.px,
                    exit_px=cur["out_ntl"] / cur["out_sz"] if cur["out_sz"] else e.px,
                    max_notional_usd=cur["max_ntl"], net_pnl_usd=cur["pnl"] - cur["fee"],
                    adds=cur["adds"], exits=cur["exits"]))
                cur = None
        if cur is not None:
            still_open += 1
    trips.sort(key=lambda t: (t.opened_ms, t.coin, t.side))
    return trips, still_open
