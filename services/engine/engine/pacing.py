"""HL read-budget pacing: stretch the poll interval as the book grows.

Hyperliquid meters /info by weight against ~1200/min per IP (services/hl
rate_limit). With up to 25 leaders, a 5 s poll can need more than that, and
the shared bucket would then make the engine's own reads (exits included)
wait. So the engine estimates one cycle's read weight and sleeps long enough
that the engine alone uses at most `BUDGET_FRAC` of the budget, leaving the
rest to the api, Scout and discovery. Never shorter than `poll_interval_s`.

Pure and deterministic: same book, same interval.

Weights (hl.rate_limit, HL docs): clearinghouseState 2 (one per dex read),
spotClearinghouseState 2, allMids 2 (one per dex). The hl venue reads, per
account, the main dex plus every HIP-3 dex the user is active on. Extras
(include_spot_staked) add a spot read and a delegator summary (2 + 20). Our own
non-funding ledger (day PnL net of transfers) is 20 every cycle (+1 per 20
rows today, negligible).
userAbstraction (20, cached 10 min) and the 5-minute full-dex rescan are
amortized and small next to the per-cycle reads, so they are left out;
`BUDGET_FRAC` keeps the headroom for them.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Set

HL_BUDGET_PER_MIN = 1200
BUDGET_FRAC = 0.60
W_CLEARINGHOUSE = 2
W_SPOT = 2
W_MIDS = 2
W_EXTRAS = 22
W_LEDGER = 20   # our own userNonFundingLedgerUpdates, every cycle (day PnL net of transfers)


def dexes_of(coins: Iterable[str]) -> Set[str]:
    """Dex keys for a set of coins: "" (main) plus each HIP-3 prefix."""
    out = {""}
    for c in coins:
        if ":" in c:
            out.add(c.split(":", 1)[0])
    return out


def account_weight(coins: Iterable[str]) -> int:
    """One account_state read: a clearinghouseState per dex + one spot read."""
    return W_CLEARINGHOUSE * len(dexes_of(coins)) + W_SPOT


def cycle_weight(our_coins: Iterable[str], leader_coins: Mapping[str, Iterable[str]],
                 include_extras: bool = False) -> int:
    """Estimated /info weight of one cycle: our account and its ledger, every leader's
    account (his active dexes), extras per leader when enabled, and one
    allMids per dex we hold copies on (mids for exits/adds)."""
    our = list(our_coins)
    w = account_weight(our) + W_LEDGER
    for coins in leader_coins.values():
        w += account_weight(coins)
        if include_extras:
            w += W_EXTRAS
    w += W_MIDS * len(dexes_of(our))
    return w


def effective_poll_s(poll_interval_s: float, weight_per_cycle: int,
                     budget_per_min: float = HL_BUDGET_PER_MIN,
                     budget_frac: float = BUDGET_FRAC) -> float:
    """max(poll_interval_s, weight * 60 / (budget * frac)): the shortest
    interval at which `weight_per_cycle` stays inside the engine's share."""
    allowed = float(budget_per_min) * float(budget_frac)
    if allowed <= 0:
        return float(poll_interval_s)
    return max(float(poll_interval_s), float(weight_per_cycle) * 60.0 / allowed)
