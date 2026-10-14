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
    gross_pnl_usd: float      # sum(closed_pnl) over the trip's fills
    fee_usd: float            # sum(fee) over the trip's fills
    funding_usd: float        # net HL userFunding settled while open, HL's sign (+ = received); 0 when not fetched
    net_pnl_usd: float        # gross_pnl_usd - fee_usd + funding_usd
    adds: int                 # entry actions after the open
    exits: int                # exit actions, the close included (>= 1)
    liquidation: bool = False  # any fill in the hold (add, reduce or the close) was a forced HL liquidation

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
                         gross_pnl_usd=round(self.gross_pnl_usd, 6), fee_usd=round(self.fee_usd, 6),
                         funding_usd=round(self.funding_usd, 6),
                         net_pnl_usd=round(self.net_pnl_usd, 6), win=self.net_pnl_usd > 0,
                         liquidation=self.liquidation)


def build_trips(fills: Sequence[Dict[str, Any]],
                funding: Optional[Sequence[Dict[str, Any]]] = None) -> Tuple[List[Trip], int]:
    """(closed trips sorted by (opened_ms, coin), number of trips still open).

    `funding`: HL userFunding rows ({time_ms, coin, usdc, ...}), same shape
    scout.metrics.round_trips takes. None (the default -- no caller here
    wires a funding fetch yet) nets every trip's funding at 0, same as
    before this field existed; a caller that fetches funding (see
    discovery.scout.stats.build_wallet for the pattern: discovery.funding_cache,
    optional on contracts.venue.Venue) gets it netted into net_pnl_usd and
    return_pct."""
    perp, _ = positions.split_perp(list(fills))
    funding_idx = positions.index_funding_by_coin(funding)
    trips: List[Trip] = []
    still_open = 0
    for coin, events in positions.reconstruct(perp).items():
        cur: Optional[Dict[str, Any]] = None
        for e in events:
            if e.kind == "open":
                if cur is not None:
                    continue    # duplicate open mid-trip (data artifact): drop it, keep the real trip
                cur = {"side": e.side, "opened": e.time_ms, "open_px": e.px,
                       "in_sz": e.delta_sz, "in_ntl": e.delta_sz * e.px, "out_sz": 0.0, "out_ntl": 0.0,
                       "pnl": e.closed_pnl, "fee": e.fee, "max_ntl": abs(e.end_position) * e.px,
                       "adds": 0, "exits": 0, "last_in": e.time_ms, "last_out": None, "liq": e.liquidation}
                continue
            if cur is None:
                continue                      # trip began before our first fill
            cur["pnl"] += e.closed_pnl
            cur["fee"] += e.fee
            cur["liq"] = cur["liq"] or e.liquidation
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
                fund = positions.funding_by_trip(funding_idx, coin, cur["opened"], e.time_ms)
                trips.append(Trip(
                    coin=coin, side=cur["side"], opened_ms=cur["opened"], closed_ms=e.time_ms,
                    open_px=cur["open_px"],
                    entry_px=cur["in_ntl"] / cur["in_sz"] if cur["in_sz"] else e.px,
                    exit_px=cur["out_ntl"] / cur["out_sz"] if cur["out_sz"] else e.px,
                    max_notional_usd=cur["max_ntl"], gross_pnl_usd=cur["pnl"], fee_usd=cur["fee"],
                    funding_usd=fund, net_pnl_usd=cur["pnl"] - cur["fee"] + fund,
                    adds=cur["adds"], exits=cur["exits"], liquidation=cur["liq"]))
                cur = None
        if cur is not None:
            still_open += 1
    trips.sort(key=lambda t: (t.opened_ms, t.coin, t.side))
    return trips, still_open
