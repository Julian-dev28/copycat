"""Per-wallet sanity trace (`python -m discovery trace --wallet 0x..`).

1. Reconstruction check: the signed position our fills imply at the end of
   the window (positions.final_positions) must equal his live account's szi
   for every perp coin he traded in-window. A mismatch means a missed page
   of fills, a wrong flip split, or a coin-name mismatch.
2. Sim trace: every copy the sim opened, its size/leverage/liq price, adds,
   closes, liquidations and the final equity.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional

from contracts.models import Settings

from . import config, db, leaderboard, positions, runner

POS_TOL = 1e-6


def compare_positions(fills: List[Dict[str, Any]], live: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows of {coin, reconstructed, live, ok} for every perp coin in fills
    or in his live positions. Pure."""
    perp, _ = positions.split_perp(fills)
    recon = positions.final_positions(perp)
    out = []
    for coin in sorted(set(recon) | set(live)):
        if not positions.is_perp_coin(coin):
            continue
        r = recon.get(coin)
        lv = float(live[coin]["szi"]) if coin in live else 0.0
        if r is None:
            # held from before the window and never traded in it: nothing to reconstruct
            out.append({"coin": coin, "reconstructed": None, "live": lv, "ok": None})
            continue
        ok = abs(r - lv) <= POS_TOL * max(1.0, abs(lv))
        out.append({"coin": coin, "reconstructed": r, "live": lv, "ok": ok})
    return out


def trace_wallet(wallet: str, settings: Settings, equity: float, days: int, venue: Optional[Any] = None,
                 max_lines: int = 60) -> Iterator[str]:
    from engine import sizing
    from hl import HlVenue
    venue = venue or HlVenue()
    wallet = wallet.strip().lower()
    conn = db.connect(config.DB_PATH)
    now_ms = int(time.time() * 1000)
    opts = runner.RunOptions(window_days=days, include_hft=True, fresh_s=0)

    # warm the cache first (can take minutes for a busy wallet), THEN read his
    # live state, then fetch only the tail up to that read: both sides of the
    # comparison describe the same instant, give or take one round trip.
    runner._sync_fills_retry(conn, venue, wallet, opts, now_ms)
    live = (venue.account_state(wallet) or {}).get("positions", {})
    now_ms = int(time.time() * 1000)
    fills = runner._sync_fills_retry(conn, venue, wallet, opts, now_ms)
    rows = compare_positions(fills, live)
    n_bad = sum(1 for r in rows if r["ok"] is False)
    yield f"{wallet}: {len(fills)} fills in {days}d, {len(rows)} perp coins, {n_bad} reconstruction mismatches"
    for r in rows:
        tag = "pre-window" if r["ok"] is None else ("ok" if r["ok"] else "MISMATCH")
        yield f"  {r['coin']:<14} reconstructed={r['reconstructed']!s:<14} live={r['live']:<14} {tag}"

    cands = [c for c in leaderboard.pull_candidates_cached(conn, venue, 0, 0, 100_000, now_ms,
                                                           config.LEADERBOARD_TTL_S) if c.address == wallet]
    cand = cands[0] if cands else leaderboard.Candidate(wallet, None, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    tr = runner.WalletTrace()
    res = runner.score_one_wallet(conn, venue, cand, settings, equity, opts, sizing, now_ms, trace=tr)
    yield (f"sim: score={res.score:.2f} ret={res.sim_return_pct:.2f}% dd={res.sim_max_drawdown_pct:.2f}% "
           f"copies={res.sim_copies} liqs={res.sim_liquidations} skipped_min={res.sim_skipped_min_order} "
           f"flags={','.join(res.flags) or '-'}")
    lines = tr.lines
    if len(lines) > max_lines:
        keep = [ln for ln in lines if " LIQ " in ln or ln.strip().startswith("end ")]
        lines = lines[: max_lines - len(keep)] + [f"  ... {len(tr.lines) - max_lines} lines elided ..."] + keep
    yield from lines
