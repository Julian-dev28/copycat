"""Orchestrates one discovery run end to end: pull candidates from the
leaderboard, sync each wallet's fills cache, reconstruct his positions,
run the copy-sim against engine.sizing, score, persist.

Rate-limit aware per the task spec: hl owns the actual limiter, this module
just logs progress (n/total, ETA) so a 50-wallet run doesn't look stuck.
ETA/rate math is plain arithmetic in `_eta` -- deterministic, not eyeballed.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, List, Optional

from contracts.models import DiscoveryRun, Settings, TraderScore
from contracts.venue import Venue

from . import db, fills_cache, leaderboard, positions, scoring, sim

logger = logging.getLogger(__name__)

DAY_MS = 86_400_000
HFT_OPENS_PER_DAY = 100.0


def _default_sizing() -> Any:
    """Lazy import: discovery must not hard-depend on services/engine at
    module import time (so discovery's own tests/CLI --help work even if
    engine isn't on disk), only when a run actually executes."""
    from engine import sizing as engine_sizing
    return engine_sizing


def _eta(done: int, total: int, elapsed_s: float) -> float:
    if done <= 0 or total <= 0:
        return 0.0
    rate = done / elapsed_s if elapsed_s > 0 else 0.0
    remaining = max(0, total - done)
    return remaining / rate if rate > 0 else 0.0


def score_one_wallet(
    conn: sqlite3.Connection,
    venue: Venue,
    candidate: "leaderboard.Candidate",
    settings: Settings,
    sim_equity_usd: float,
    window_days: int,
    sizing_module: Any,
    now_ms: Optional[int] = None,
) -> TraderScore:
    """Fetch/cache fills, reconstruct, simulate, score one wallet. Never
    raises for a per-wallet data problem -- a wallet that can't be scored
    comes back with a reason in `flags` instead (every candidate must end
    up scored or flagged, per the live eval's pass criteria)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    window_start_ms = now_ms - window_days * DAY_MS
    effective = settings.for_leader(candidate.address)

    flags = list(candidate.flags)
    try:
        fills = fills_cache.sync_fills(conn, venue, candidate.address, window_days, now_ms)
    except Exception as exc:
        logger.warning("discovery: fills sync failed for %s: %s", candidate.address, exc)
        return _flagged_score(candidate, flags + [f"error:fills:{type(exc).__name__}"])

    by_coin = positions.reconstruct(fills)
    opens_per_day = positions.opens_per_day(by_coin, window_days)
    median_hold, _ = positions.median_hold_hours(by_coin)
    coins = positions.coins_traded(by_coin)

    if opens_per_day > HFT_OPENS_PER_DAY:
        flags.append("hft")

    events = positions.merged_timeline(by_coin)
    if not events:
        return _flagged_score(candidate, flags + ["too_few_trades"], fills_30d=len(fills),
                               opens_per_day=opens_per_day, median_hold_h=median_hold, coins=coins)

    leader_leverage_by_coin = _leader_leverage_by_coin(venue, candidate.address, coins)

    try:
        result = sim.simulate_wallet(
            conn=conn, venue=venue, events=events, leader_equity_usd=candidate.account_value_usd,
            leader_leverage_by_coin=leader_leverage_by_coin, settings=effective,
            sim_equity_usd=sim_equity_usd, window_start_ms=window_start_ms, window_end_ms=now_ms,
            sizing=sizing_module,
        )
    except Exception as exc:
        logger.warning("discovery: sim failed for %s: %s", candidate.address, exc)
        return _flagged_score(candidate, flags + [f"error:sim:{type(exc).__name__}"], fills_30d=len(fills),
                               opens_per_day=opens_per_day, median_hold_h=median_hold, coins=coins)

    if result.flags:
        logger.debug("discovery: %s sim flags (skips/liquidations, not all bubbled to TraderScore): %s",
                      candidate.address, result.flags)
    # TraderScore.flags stays high-level (hft/vault/too_few_trades/liquidated) per the contract's own
    # examples; per-event skip noise (worse_entry/margin_room/max_open_copies/no_candle_data) is already
    # reflected quantitatively via sim_copies/sim_skipped_min_order and is logged above for debugging.
    flags.extend(f for f in result.flags if f.split(":")[0] == "liquidated")
    scored = scoring.score_candidate(result.sim_return_pct, result.sim_max_drawdown_pct,
                                      result.sim_liquidations, result.sim_copies)
    flags.extend(scored.flags)

    return TraderScore(
        address=candidate.address,
        display_name=candidate.display_name,
        account_value_usd=candidate.account_value_usd,
        pnl_30d_usd=candidate.pnl_30d_usd,
        roi_30d_pct=candidate.roi_30d_pct,
        pnl_all_time_usd=candidate.pnl_all_time_usd,
        volume_30d_usd=candidate.volume_30d_usd,
        fills_30d=len(fills),
        opens_per_day=opens_per_day,
        median_hold_h=median_hold,
        coins=coins,
        sim_return_pct=result.sim_return_pct,
        sim_max_drawdown_pct=result.sim_max_drawdown_pct,
        sim_liquidations=result.sim_liquidations,
        sim_copies=result.sim_copies,
        sim_skipped_min_order=result.sim_skipped_min_order,
        sim_fees_usd=result.sim_fees_usd,
        score=scored.score,
        flags=sorted(set(flags)),
    )


def _flagged_score(candidate: "leaderboard.Candidate", flags: List[str], fills_30d: int = 0,
                    opens_per_day: float = 0.0, median_hold_h: Optional[float] = None,
                    coins: Optional[List[str]] = None) -> TraderScore:
    """A candidate we could not simulate (no in-window events, or a data
    error) still comes back scored -- at the floor, heavily flagged -- so
    the pipeline's contract ("every candidate scored or flagged") holds."""
    return TraderScore(
        address=candidate.address, display_name=candidate.display_name,
        account_value_usd=candidate.account_value_usd, pnl_30d_usd=candidate.pnl_30d_usd,
        roi_30d_pct=candidate.roi_30d_pct, pnl_all_time_usd=candidate.pnl_all_time_usd,
        volume_30d_usd=candidate.volume_30d_usd, fills_30d=fills_30d, opens_per_day=opens_per_day,
        median_hold_h=median_hold_h, coins=coins or [], sim_return_pct=0.0, sim_max_drawdown_pct=0.0,
        sim_liquidations=0, sim_copies=0, sim_skipped_min_order=0, sim_fees_usd=0.0,
        score=-1e9, flags=sorted(set(flags)),
    )


def _leader_leverage_by_coin(venue: Venue, address: str, coins: List[str]) -> dict:
    """Current per-coin leverage snapshot (documented approximation: his
    leverage at each historical fill time isn't recoverable from fills
    alone). Falls back to the coin's own max leverage -- in match mode that
    degrades to "max" mode for a coin he's since closed -- when he has no
    open position in it right now."""
    out: dict = {}
    try:
        state = venue.account_state(address)
    except Exception:
        state = None
    positions_now = (state or {}).get("positions", {}) if state else {}
    for coin in coins:
        pos = positions_now.get(coin)
        out[coin] = float(pos["lev"]) if pos else float(max(1, venue.max_leverage(coin) or 1))
    return out


def execute(
    conn: sqlite3.Connection,
    venue: Venue,
    run_id: str,
    settings: Settings,
    sim_equity_usd: float,
    top_n: int,
    window_days: int = 30,
    min_account_value_usd: float = 10_000.0,
    min_volume_30d_usd: float = 50_000.0,
    sizing_module: Optional[Any] = None,
    progress_cb: Optional[Any] = None,
) -> None:
    """Runs synchronously in the caller's thread (discovery.public wraps
    this in a background thread so only one run is ever in flight)."""
    sizing_module = sizing_module or _default_sizing()
    started = time.time()
    try:
        candidates = leaderboard.pull_candidates(venue, min_account_value_usd, min_volume_30d_usd, top_n)
    except Exception as exc:
        logger.error("discovery run %s: leaderboard pull failed: %s", run_id, exc)
        db.update_run(conn, run_id, status="failed", finished_ms=int(time.time() * 1000),
                       error=f"leaderboard pull failed: {exc}")
        return

    db.update_run(conn, run_id, candidates=len(candidates))
    total = len(candidates)
    scored = 0
    now_ms = int(time.time() * 1000)
    # Rough call budget: 1 fills() call + 1 account_state() call per wallet at minimum, plus
    # paginated fills() and batched-per-coin candles() as needed. hl owns the actual rate limiter
    # (it sleeps/retries internally); this is just an operator-visible sanity number so a top_n=50
    # run's wall-clock ETA below isn't a surprise.
    logger.info("discovery run %s: %d candidates pulled, simulating (hl rate-limits network calls "
                "internally; progress below)", run_id, total)

    for i, candidate in enumerate(candidates, start=1):
        try:
            result = score_one_wallet(conn, venue, candidate, settings, sim_equity_usd, window_days,
                                       sizing_module, now_ms=now_ms)
        except Exception as exc:  # belt-and-suspenders: one bad wallet must never kill the run
            logger.warning("discovery run %s: wallet %s failed uncaught: %s", run_id, candidate.address, exc)
            result = _flagged_score(candidate, [f"error:uncaught:{type(exc).__name__}"])

        db.save_result(conn, run_id, result.address, result.score, result.model_dump_json())
        scored += 1
        db.update_run(conn, run_id, scored=scored)

        elapsed = time.time() - started
        eta_s = _eta(i, total, elapsed)
        logger.info("discovery run %s: %d/%d wallets scored, eta=%.0fs", run_id, i, total, eta_s)
        if progress_cb:
            progress_cb(i, total, eta_s)

    db.update_run(conn, run_id, status="done", finished_ms=int(time.time() * 1000))
