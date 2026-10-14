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
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

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
    # HL's own fill classifies as a forced liquidation when its `dir` starts with
    # "Liquidated" (same check as scout.metrics.real_liquidations; the venue's separate
    # `liquidation` bool column is NOT used here -- measured 2026-10-14 on a real wallet
    # that is the counterparty absorbing someone ELSE's liquidation: HL sets that bool on
    # the counterparty's own ordinary "Open Long" fill too, so it does not mean "this
    # account got liquidated", only "a liquidation engine fill touched this account").
    # On a flip this is set on the close leg only: a forced liquidation closes/reduces a
    # position, it never opens a new one, so the synthetic open half is never flagged.
    liquidation: bool = False


def _side_of(signed: float) -> Side:
    return "long" if signed > 0 else "short"


# A position is "flat" within this tolerance, not only at exactly 0.0.
# Measured 2026-10-14 on a real HIP-3 wallet's aggregateByTime fills (sz in
# the low millions on coin "W"): a run of adds/reduces that should close
# flat to flat left `start + signed sz` at 4.66e-10, 9.31e-10 and 1.16e-10
# instead of 0.0 -- 2^-31, 2^-30 and 2^-33 exactly, a float32-precision
# artifact somewhere in HL's own server-side aggregation of the sz sum, not
# ours. With the old EXACT `== 0` check those three closes were missed
# entirely: reconstruct() kept the coin "open" forever, every later fill on
# it became an add/reduce against a phantom residual position, and
# round_trips() emitted zero trips for it instead of three -- silently
# dropping $887,706 of this wallet's real 30d realized PnL from the trader
# file. 1e-6 is far below any coin's real minimum size increment (even
# szDecimals=5 is 1e-5) and far above the observed float-precision residue.
_FLAT_EPS = 1e-6


def _is_flat(x: float) -> float:
    """Snap a position to exactly 0.0 within _FLAT_EPS; otherwise unchanged."""
    return 0.0 if abs(x) < _FLAT_EPS else x


def _classify_one(coin: str, time_ms: int, start: float, end: float, px: float,
                   fee: float, closed_pnl: float, liquidation: bool = False) -> List[PositionEvent]:
    start, end = _is_flat(start), _is_flat(end)
    if start == 0 and end == 0:
        return []
    if start == 0:
        return [PositionEvent(coin, time_ms, "open", _side_of(end), abs(end), start, end, px, fee, closed_pnl,
                              liquidation)]
    if end == 0:
        return [PositionEvent(coin, time_ms, "close", _side_of(start), abs(start), start, end, px, fee, closed_pnl,
                              liquidation)]
    same_side = (start > 0) == (end > 0)
    if same_side:
        kind: Kind = "add" if abs(end) > abs(start) else "reduce"
        return [PositionEvent(coin, time_ms, kind, _side_of(start), abs(abs(end) - abs(start)),
                               start, end, px, fee, closed_pnl, liquidation)]
    # flip: close the old side entirely, then open the new side entirely. A forced
    # liquidation can force-close (or force-reduce) a position; it never opens a new
    # one, so only the close leg ever carries the flag.
    close_evt = PositionEvent(coin, time_ms, "close", _side_of(start), abs(start), start, 0.0,
                               px, fee, closed_pnl, liquidation)
    open_evt = PositionEvent(coin, time_ms, "open", _side_of(end), abs(end), 0.0, end, px, 0.0, 0.0, False)
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
        liq = str(f.get("dir") or "").startswith("Liquidated")
        events = _classify_one(f["coin"], int(f["time_ms"]), start, end, float(f["px"]),
                                float(f.get("fee", 0.0)), float(f.get("closed_pnl", 0.0)), liq)
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


# ── perp filter, poll coalescing, trips ───────────────────────────────────

def is_perp_coin(coin: str) -> bool:
    """Perp coins are a main-dex name ("BTC", "kPEPE") or a HIP-3 "dex:NAME".
    Fills also carry spot pairs ("@151", "PURR/USDC") and outcome markets
    ("#12100"); candleSnapshot 500s on those and the engine never copies them."""
    if not coin or coin[0] in "@#" or "/" in coin:
        return False
    return True


def split_perp(fills: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    perp, other = [], []
    for f in fills:
        (perp if is_perp_coin(str(f["coin"])) else other).append(f)
    return perp, other


def _signed(f: Dict[str, Any]) -> float:
    return abs(float(f["sz"])) * (1.0 if f["side"] == "B" else -1.0)


def coalesce_by_poll(fills: List[Dict[str, Any]], poll_ms: int) -> List[Dict[str, Any]]:
    """Collapse each coin's fills inside one engine poll interval into one
    net synthetic fill, because the live engine only sees the leader's
    position once per `poll_interval_s`: 40 partial fills of one TWAP slice
    are one "add" to it, and an open+close inside one poll is invisible.

    The synthetic fill keeps the bucket's first start_position, the net
    signed size, the size-weighted average price, the last fill's time, and
    the summed fee / closed_pnl. A bucket that nets to zero change is kept
    (classify drops 0 -> 0 itself). Fills at the same ms are ordered by
    chaining start_position -> end so the bucket's start is the true start.
    """
    if poll_ms <= 0:
        return sorted(fills, key=lambda f: f["time_ms"])
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for f in fills:
        buckets.setdefault((f["coin"], int(f["time_ms"]) // poll_ms), []).append(f)
    out: List[Dict[str, Any]] = []
    for (coin, _), fs in buckets.items():
        fs.sort(key=lambda f: f["time_ms"])
        if len(fs) == 1:
            out.append(fs[0])
            continue
        t0 = fs[0]["time_ms"]
        firsts = [f for f in fs if f["time_ms"] == t0]
        ends = {round(float(f["start_position"]) + _signed(f), 12) for f in fs}
        first = next((f for f in firsts if round(float(f["start_position"]), 12) not in ends), firsts[0])
        net = sum(_signed(f) for f in fs)
        gross = sum(abs(float(f["sz"])) for f in fs)
        px = sum(abs(float(f["sz"])) * float(f["px"]) for f in fs) / gross if gross else float(fs[-1]["px"])
        out.append({
            "time_ms": int(fs[-1]["time_ms"]), "coin": coin, "px": px, "sz": abs(net),
            "side": "B" if net >= 0 else "A", "start_position": float(first["start_position"]),
            "fee": sum(float(f.get("fee", 0.0)) for f in fs),
            "closed_pnl": sum(float(f.get("closed_pnl", 0.0)) for f in fs),
        })
    out.sort(key=lambda f: f["time_ms"])
    return out


def final_positions(fills: List[Dict[str, Any]]) -> Dict[str, float]:
    """Signed position per coin right after the last fill we have for it:
    last fill's start_position + its signed size. This is what the leader's
    live account must show for every coin he traded in-window, unless he
    traded it again after our fetch."""
    last: Dict[str, Dict[str, Any]] = {}
    for f in sorted(fills, key=lambda r: r["time_ms"]):
        last[f["coin"]] = f
    return {c: float(f["start_position"]) + _signed(f) for c, f in last.items()}


def index_funding_by_coin(funding: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, List[Tuple[int, float]]]:
    """Group HL `userFunding` rows ({time_ms, coin, usdc, ...}) by coin, sorted
    by time, for repeated window sums (`funding_by_trip`). None/empty in ->
    empty out: a wallet with no funding reads (old stats, a failed fetch)
    nets 0, never fabricated."""
    out: Dict[str, List[Tuple[int, float]]] = {}
    for f in funding or []:
        out.setdefault(str(f["coin"]), []).append((int(f["time_ms"]), float(f["usdc"])))
    for coin in out:
        out[coin].sort()
    return out


def funding_by_trip(by_coin: Dict[str, List[Tuple[int, float]]], coin: str, opened_ms: int, closed_ms: int) -> float:
    """Net funding (HL's sign: positive = received, negative = paid) settled
    for `coin` while this trip's position was open: [opened_ms, closed_ms).
    Half-open so a settlement at the exact close instant (already flat)
    lands on whichever trip opens next, never double-counted. A coin absent
    from `by_coin` (no funding events at all, or an un-synced cache) nets 0."""
    return sum(usdc for t, usdc in by_coin.get(coin, ()) if opened_ms <= t < closed_ms)


def trip_spans(by_coin: Dict[str, List[PositionEvent]], window_end_ms: int) -> Dict[str, List[Tuple[int, int]]]:
    """Per coin, the [open, close] time ranges of every trip that OPENS in
    the window (still-open trips run to window_end_ms). Only these can carry
    a copy, so only these need candles."""
    out: Dict[str, List[Tuple[int, int]]] = {}
    for coin, events in by_coin.items():
        open_t: Optional[int] = None
        for e in events:
            if e.kind == "open":
                open_t = e.time_ms
            elif e.kind == "close" and open_t is not None:
                out.setdefault(coin, []).append((open_t, e.time_ms))
                open_t = None
        if open_t is not None:
            out.setdefault(coin, []).append((open_t, window_end_ms))
    return out
