"""Coattail-rider detector (user_consensus_2026-10 P1 #6).

Hyperdash's own docs warn that an "algorithmic" wallet "may not replicate
their results due to execution speed differences". A coattail-rider is a
related but distinct failure mode: the wallet isn't fast, it's derivative.
It consistently re-enters another top-ranked wallet's position seconds to
minutes later, on the same coin and side, so copying IT just stacks a
second layer of latency on top of whatever edge the real source wallet has
(documented on Hyperliquid's own leaderboard: see coinmarketman, "the
wallets copying Hyperliquid's top 10").

Pure function over already-cached opens (no HL calls, no state, no clock).
Bucketed by (coin, side) and swept once in time order, so this is
O(E log E) over E open events, not O(E^2) over the whole cohort.

This is a heuristic, not a proof: two wallets can legitimately react to the
same public news within seconds with no relationship at all. The gates
(MIN_OPENS, MIN_SHARE) are deliberately conservative, and callers must
present this as "opens often land soon after X's, which may mean no
independent edge" -- not as a fact.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

LAG_MIN_MS = 1_000         # ignore near-simultaneous fills (same block/event, not a lag)
LAG_MAX_MS = 120_000       # "seconds to minutes" per the research doc
MIN_OPENS = 5              # minimum opens before trusting the pattern at all
MIN_SHARE = 0.5            # share of a wallet's opens that must lag the SAME leader


@dataclass(frozen=True)
class Open:
    address: str
    coin: str
    side: str              # "long" | "short"
    t_ms: int


def opens_from_fills(address: str, fills: Sequence[Dict[str, object]]) -> List[Open]:
    """HL's own fill `dir` says "Open Long" / "Open Short" directly; no
    reconstruction needed (that's for round trips, which this doesn't need)."""
    out: List[Open] = []
    for f in fills:
        d = str(f.get("dir") or "")
        if d == "Open Long":
            out.append(Open(address, str(f["coin"]), "long", int(f["time_ms"])))
        elif d == "Open Short":
            out.append(Open(address, str(f["coin"]), "short", int(f["time_ms"])))
    return out


def detect_coattails(opens: Sequence[Open]) -> Dict[str, Tuple[str, float, int]]:
    """address -> (leader_address, share, matched_count) for every wallet
    whose opens lag ONE other wallet's same-coin/same-side opens by
    [LAG_MIN_MS, LAG_MAX_MS] at least MIN_SHARE of the time, over >= MIN_OPENS
    opens. Each open is matched to its single nearest preceding candidate
    (not every wallet that happened to open earlier), so a crowded coin
    doesn't inflate matches."""
    buckets: Dict[Tuple[str, str], List[Open]] = defaultdict(list)
    for o in opens:
        buckets[(o.coin, o.side)].append(o)

    matches: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: Dict[str, int] = defaultdict(int)

    for evs in buckets.values():
        evs = sorted(evs, key=lambda e: e.t_ms)
        lo = 0
        for i, e in enumerate(evs):
            totals[e.address] += 1
            while evs[lo].t_ms < e.t_ms - LAG_MAX_MS:
                lo += 1
            best_leader, best_lag = None, None
            for j in range(i - 1, lo - 1, -1):
                cand = evs[j]
                lag = e.t_ms - cand.t_ms
                if lag < LAG_MIN_MS or cand.address == e.address:
                    continue
                if best_lag is None or lag < best_lag:
                    best_leader, best_lag = cand.address, lag
            if best_leader is not None:
                matches[e.address][best_leader] += 1

    out: Dict[str, Tuple[str, float, int]] = {}
    for addr, total in totals.items():
        if total < MIN_OPENS or not matches[addr]:
            continue
        leader, count = max(matches[addr].items(), key=lambda kv: kv[1])
        share = count / total
        if share >= MIN_SHARE:
            out[addr] = (leader, round(share, 4), count)
    return out
