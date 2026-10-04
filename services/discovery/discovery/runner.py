"""One discovery run end to end: leaderboard -> per wallet (fills, perp
filter, poll coalescing, reconstruct, HFT gate, candles for trip spans,
copy-sim, score) -> persist.

Wallets run on a small thread pool (WORKERS). The HL budget is the real
bottleneck and hl's shared limiter paces every call; the pool only hides
round-trip latency (~0.3-2s per call) behind other wallets' calls. Each
thread has its own sqlite connection; candle fetches for one coin are
serialized by a per-coin lock so two wallets never fetch the same bars.

Progress: `runs.scored / runs.candidates` plus `runs.heartbeat_ms`, updated
after every wallet. The CLI turns those into an ETA (no contract change).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from contracts.models import LeverageMode, Settings, TraderScore
from contracts.venue import Venue

from . import candles_cache, config, db, fills_cache, leaderboard, positions, scoring, sim

logger = logging.getLogger(__name__)

DAY_MS = 86_400_000
HFT_OPENS_PER_DAY = 100.0
WORKERS = 4
FILLS_RETRIES = 3
FILLS_RETRY_S = 10.0


class SerialVenue:
    """Proxy that lets only ONE Venue call from this run be in flight at a
    time. The HL budget (20 weight/s) is the throughput ceiling, so
    concurrent calls buy nothing; they only make every thread queue at hl's
    limiter, where a 120-weight fills page could wait past hl's 30s
    max_wait and come back None (measured: 18 such failures in one run with
    4 unserialized workers). Threads still overlap sqlite and sim CPU."""

    def __init__(self, venue: Venue):
        self._venue = venue
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._venue, name)
        if not callable(attr):
            return attr

        def call(*a: Any, **kw: Any) -> Any:
            with self._lock:
                return attr(*a, **kw)
        call.__wrapped__ = attr   # keeps inspect.signature (aggregate_by_time detection) truthful
        return call


def _default_sizing() -> Any:
    from engine import sizing as engine_sizing   # lazy: discovery imports without engine on disk
    return engine_sizing


def eta_s(done: int, total: int, elapsed_s: float) -> Optional[float]:
    """Seconds left at the average rate so far. None before the first wallet."""
    if done <= 0 or total <= 0 or elapsed_s <= 0:
        return None
    return max(0, total - done) * (elapsed_s / done)


@dataclass
class RunOptions:
    window_days: int = config.DEFAULT_WINDOW_DAYS
    min_account_value_usd: float = config.DEFAULT_MIN_ACCOUNT_VALUE_USD
    min_volume_30d_usd: float = config.DEFAULT_MIN_VOLUME_30D_USD
    include_hft: bool = False
    fresh_s: float = config.CACHE_FRESH_S
    leaderboard_ttl_s: float = config.LEADERBOARD_TTL_S
    workers: int = WORKERS

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, s: Optional[str]) -> "RunOptions":
        try:
            d = json.loads(s or "{}")
        except ValueError:
            d = {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class WalletTrace:
    """What happened to one wallet, for the CLI's --trace and the sanity check."""
    lines: List[str] = field(default_factory=list)

    def __call__(self, line: str) -> None:
        self.lines.append(line)


def _flagged(c: "leaderboard.Candidate", flags: List[str], fills_n: int = 0, opd: float = 0.0,
             hold: Optional[float] = None, coins: Optional[List[str]] = None) -> TraderScore:
    """A wallet we did not simulate: lowest band, with the reason in flags."""
    return TraderScore(
        address=c.address, display_name=c.display_name, account_value_usd=c.account_value_usd,
        pnl_30d_usd=c.pnl_30d_usd, roi_30d_pct=c.roi_30d_pct, pnl_all_time_usd=c.pnl_all_time_usd,
        volume_30d_usd=c.volume_30d_usd, fills_30d=fills_n, opens_per_day=opd, median_hold_h=hold,
        coins=coins or [], sim_return_pct=0.0, sim_max_drawdown_pct=0.0, sim_liquidations=0, sim_copies=0,
        sim_skipped_min_order=0, sim_fees_usd=0.0, score=scoring.UNSCORED, flags=sorted(set(flags)),
    )


def _sync_fills_retry(conn: sqlite3.Connection, venue: Venue, address: str, opts: RunOptions,
                      now_ms: int) -> List[Dict[str, Any]]:
    for attempt in range(FILLS_RETRIES):
        try:
            return fills_cache.sync_fills(conn, venue, address, opts.window_days, now_ms, opts.fresh_s)
        except fills_cache.FillsFetchError:
            if attempt == FILLS_RETRIES - 1:
                raise
            time.sleep(FILLS_RETRY_S * (attempt + 1))
    raise AssertionError("unreachable")


def _leader_leverage(venue: Venue, address: str, settings: Settings, coins: List[str]) -> Dict[str, float]:
    """Only leverage_mode=match needs his leverage (a CURRENT snapshot; his
    leverage at each historical fill is not recoverable). Every other mode
    ignores it, so no account_state read is spent."""
    if settings.leverage_mode != LeverageMode.match:
        return {}
    try:
        state = venue.account_state(address)
    except Exception:
        state = None
    now = (state or {}).get("positions", {}) or {}
    return {c: float(now[c]["lev"]) for c in coins if c in now}


@dataclass
class Prepared:
    """One wallet, ready to simulate. Shared by score_one_wallet and Scout's
    simstage. `skip` set means do not simulate; it holds the flags that say
    why (they go into TraderScore.flags as-is)."""
    flags: List[str]
    n_fills: int
    opens_per_day: float
    median_hold_h: Optional[float]
    coins: List[str]
    events: List[positions.PositionEvent] = field(default_factory=list)
    series: Dict[str, candles_cache.Series] = field(default_factory=dict)
    coin_max_lev: Dict[str, int] = field(default_factory=dict)
    skip: Optional[List[str]] = None


def prepare_wallet(conn: sqlite3.Connection, venue: Any, fills: List[Dict[str, Any]], settings: Settings,
                   window_days: int, now_ms: int, include_hft: bool = False,
                   fresh_s: float = config.CACHE_FRESH_S, coin_max_lev: Optional[Dict[str, int]] = None,
                   cache_only: bool = False, stats: Optional[Dict[str, int]] = None) -> Prepared:
    """Perp filter, poll coalescing (settings.poll_interval_s), reconstruct,
    HFT gate, then candles only for trip spans. `coin_max_lev`: known max
    leverage per coin (skips venue.max_leverage for those). `cache_only`:
    never ask the venue for leverage, and a candle read that fails is not
    flagged (the caller passes a venue that answers None on purpose)."""
    ws = now_ms - window_days * DAY_MS
    flags: List[str] = []
    perp, other = positions.split_perp(fills)
    if other:
        flags.append("non_perp_ignored")
    by_coin = positions.reconstruct(positions.coalesce_by_poll(perp, int(settings.poll_interval_s * 1000)))
    p = Prepared(flags=flags, n_fills=len(fills), opens_per_day=positions.opens_per_day(by_coin, window_days),
                 median_hold_h=positions.median_hold_hours(by_coin)[0], coins=positions.coins_traded(by_coin))
    if p.opens_per_day > HFT_OPENS_PER_DAY:
        flags.append("hft")
        if not include_hft:
            p.skip = ["hft_not_simulated"]
            return p
    spans = positions.trip_spans(by_coin, now_ms)
    if not spans:
        p.skip = ["too_few_trades"]
        return p
    known = dict(coin_max_lev or {})
    for coin, sp in spans.items():
        lev = int(known.get(coin) or 0)
        if lev < 1 and not cache_only:
            lev = int(venue.max_leverage(coin) or 0)
        p.coin_max_lev[coin] = lev
        if lev < 1:
            continue   # the sim flags it; no candles for a coin it will never open
        p.series[coin], ok = candles_cache.build_series(conn, venue, coin, sp, now_ms, fresh_s, stats)
        if not ok and not cache_only:
            flags.append(f"candles_partial:{coin}")
    p.events = [e for e in positions.merged_timeline(by_coin) if e.time_ms >= ws]
    return p


def simulate_prepared(p: Prepared, venue: Any, address: str, settings: Settings, sim_equity_usd: float,
                      leader_equity_usd: float, sizing_module: Any, now_ms: int,
                      trace: Optional[WalletTrace] = None, **sim_kw: Any) -> "sim.SimResult":
    """The copy-sim on a Prepared wallet. Raw SimResult, skip flags intact
    (worse_entry / margin_room / max_open_copies / add_capped / ...)."""
    return sim.simulate_wallet(events=p.events, series=p.series, coin_max_lev=p.coin_max_lev,
                               leader_equity_usd=leader_equity_usd,
                               leader_leverage_by_coin=_leader_leverage(venue, address, settings, p.coins),
                               settings=settings, sim_equity_usd=sim_equity_usd, window_end_ms=now_ms,
                               sizing=sizing_module, trace=trace, **sim_kw)


def score_one_wallet(conn: sqlite3.Connection, venue: Venue, c: "leaderboard.Candidate", settings: Settings,
                     sim_equity_usd: float, opts: RunOptions, sizing_module: Any, now_ms: int,
                     stats: Optional[Dict[str, int]] = None, trace: Optional[WalletTrace] = None) -> TraderScore:
    """Never raises for a per-wallet data problem: every wallet comes back
    scored, or in the lowest band with the reason in flags."""
    es = settings.for_leader(c.address)
    try:
        fills = _sync_fills_retry(conn, venue, c.address, opts, now_ms)
    except fills_cache.FillsFetchError:
        return _flagged(c, list(c.flags) + ["error:fills_read_failed"])

    p = prepare_wallet(conn, venue, fills, es, opts.window_days, now_ms, opts.include_hft, opts.fresh_s,
                       stats=stats)
    flags = list(c.flags) + p.flags
    if p.skip is not None:
        return _flagged(c, flags + p.skip, p.n_fills, p.opens_per_day, p.median_hold_h, p.coins)
    try:
        r = simulate_prepared(p, venue, c.address, es, sim_equity_usd, c.account_value_usd, sizing_module, now_ms,
                              trace)
    except Exception as exc:
        logger.warning("discovery: sim failed for %s: %s", c.address, exc, exc_info=True)
        return _flagged(c, flags + [f"error:sim:{type(exc).__name__}"], p.n_fills, p.opens_per_day,
                        p.median_hold_h, p.coins)

    flags.extend(sorted({f for f in r.flags if f.startswith(("liquidated:", "max_leverage_unknown:"))}))
    sc = scoring.score_candidate(r.sim_return_pct, r.sim_max_drawdown_pct, r.sim_liquidations, r.sim_copies)
    flags.extend(sc.flags)
    return TraderScore(
        address=c.address, display_name=c.display_name, account_value_usd=c.account_value_usd,
        pnl_30d_usd=c.pnl_30d_usd, roi_30d_pct=c.roi_30d_pct, pnl_all_time_usd=c.pnl_all_time_usd,
        volume_30d_usd=c.volume_30d_usd, fills_30d=p.n_fills, opens_per_day=p.opens_per_day,
        median_hold_h=p.median_hold_h, coins=p.coins, sim_return_pct=round(r.sim_return_pct, 4),
        sim_max_drawdown_pct=round(r.sim_max_drawdown_pct, 4), sim_liquidations=r.sim_liquidations,
        sim_copies=r.sim_copies, sim_skipped_min_order=r.sim_skipped_min_order,
        sim_fees_usd=round(r.sim_fees_usd, 6), score=round(sc.score, 6), flags=sorted(set(flags)),
    )


def execute(conn: sqlite3.Connection, venue: Venue, run_id: str, settings: Settings, sim_equity_usd: float,
            top_n: int, opts: Optional[RunOptions] = None, sizing_module: Optional[Any] = None,
            db_path: Optional[Any] = None,
            progress_cb: Optional[Callable[[int, int, Optional[float]], None]] = None) -> None:
    """Runs synchronously in the caller's thread. `db_path`: where worker
    threads open their own connections (defaults to config.DB_PATH)."""
    opts = opts or RunOptions()
    sizing_module = sizing_module or _default_sizing()
    db_path = db_path or config.DB_PATH
    venue = SerialVenue(venue)
    started = time.time()
    now_ms = int(started * 1000)
    try:
        candidates = leaderboard.pull_candidates_cached(conn, venue, opts.min_account_value_usd,
                                                        opts.min_volume_30d_usd, top_n, now_ms,
                                                        opts.leaderboard_ttl_s)
    except Exception as exc:
        logger.error("discovery run %s: leaderboard pull failed: %s", run_id, exc)
        db.update_run(conn, run_id, status="failed", finished_ms=int(time.time() * 1000),
                      error=f"leaderboard pull failed: {exc}")
        return

    total = len(candidates)
    db.update_run(conn, run_id, candidates=total, heartbeat_ms=int(time.time() * 1000))
    logger.info("discovery run %s: %d candidates (leaderboard %.1fs)", run_id, total, time.time() - started)
    stats: Dict[str, int] = {}
    lock = threading.Lock()
    done = 0

    def work(c: "leaderboard.Candidate") -> TraderScore:
        wconn = db.connect(db_path)
        t0 = time.time()
        try:
            res = score_one_wallet(wconn, venue, c, settings, sim_equity_usd, opts, sizing_module, now_ms, stats)
        except Exception as exc:   # one bad wallet must never kill the run
            logger.warning("discovery run %s: %s failed uncaught: %s", run_id, c.address, exc, exc_info=True)
            res = _flagged(c, [f"error:uncaught:{type(exc).__name__}"])
        logger.info("discovery run %s: %s scored in %.1fs (fills=%d copies=%d)", run_id, c.address,
                    time.time() - t0, res.fills_30d, res.sim_copies)
        return res

    with ThreadPoolExecutor(max_workers=max(1, opts.workers), thread_name_prefix="discovery") as pool:
        futs = [pool.submit(work, c) for c in candidates]
        for fut in as_completed(futs):
            res = fut.result()
            with lock:
                db.save_result(conn, run_id, res.address, res.score, res.model_dump_json())
                done += 1
                db.update_run(conn, run_id, scored=done, heartbeat_ms=int(time.time() * 1000))
                eta = eta_s(done, total, time.time() - started)
                logger.info("discovery run %s: %d/%d scored, eta=%s", run_id, done, total,
                            "?" if eta is None else f"{eta:.0f}s")
                if progress_cb:
                    progress_cb(done, total, eta)

    db.update_run(conn, run_id, status="done", finished_ms=int(time.time() * 1000),
                  heartbeat_ms=int(time.time() * 1000))
    logger.info("discovery run %s: done in %.1fs, %d candle calls", run_id, time.time() - started,
                stats.get("candle_calls", 0))
