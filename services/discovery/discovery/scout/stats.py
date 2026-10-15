"""Stage B: per-wallet stats (spec 7.2), budgeted.

Per wallet: `portfolio` (20), an incremental `userFillsByTime` sync through
discovery's fills cache (20 per page + 1 per 20 rows, so 21 for a 12-row
warm tail and 120 for a full 2000-row page; pages capped per pass), and, on
a FULL pass only, `account_state` (~8), `extras` (~22), `userFunding` (20
per page + 1 per 20 rows, 45 for a full 500-row page) and the one-time
liquidation backfill. From those, deterministic metrics (scout.metrics)
into scout_stats.

Warm path (indexing tightening, 2026-10): a wallet with stats already on
disk pays for the cheap set (portfolio + fills tail) on most passes. The
expensive set moves to a slower cadence, `config.FULL_REFRESH_EVERY_S`
(default 6h), tracked per wallet in `scout_stats.full_ms` -- UNLESS a new
fill just landed (the account genuinely changed) or this is the wallet's
first-ever build, either of which forces a full pass right away. See
`build_wallet`'s docstring for exactly what is reused vs re-fetched.

All-or-nothing per wallet: if any read fails, nothing is written for it
(its previous stats keep serving), fail_count goes up, and at 2 failures in
a row it sits out one cycle and its row is flagged `stale`.

Order: wallets in the user's book first, then on-demand requests, then
stalest first (never-built wallets count as stalest). The pass stops at the
first wallet whose estimated weight would cross the budget, or when the wall
clock budget is spent; the rest go first next pass (this, plus stalest-
first ordering, is what guarantees every wallet rotates through within two
passes -- see test_scout_refresh.py's rotation test).

The budget is charged by what the wallet ACTUALLY called (CountingVenue),
weights per services/hl/hl/rate_limit.py. Per-wallet weight, pages and
seconds are logged at DEBUG, summarized at INFO per pass (p50/p95 weight,
pages, seconds; top 5 most expensive wallets) and the summary is stored in
scout_meta under "stage_b_summary" for the README eval to read.
"""
from __future__ import annotations

import inspect
import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from contracts.models import PnlWindow
from contracts.venue import Venue

from .. import config as discovery_config
from .. import fills_cache, funding_cache
from . import config as C
from . import metrics as M
from . import store

try:
    from hl import rate_limit as _hl_rate_limit  # the HL bucket's wait meter (bucket_waited_s)
except ImportError:  # pragma: no cover - a venue-less checkout; the summary then reports 0 wait
    _hl_rate_limit = None

logger = logging.getLogger(__name__)


def _params(fn: Any) -> Sequence[str]:
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return []


class CountingVenue:
    """Wraps a Venue and charges HL weight for every read made through it.

    Paginated reads (fills, funding) are billed what HL metered for them:
    the wrapped venue's own count when it keeps one (`HlVenue.last_read`:
    pages that came back and their weight, straight from the responses),
    else the documented rule on the rows handed back (W_INFO per page + 1
    per ITEMS_PER_WEIGHT rows). The rule is exact for a one-page read and a
    lower bound once `aggregate_by_time` merged partial fills; the page cap
    (W_FILLS_PAGE, 120) is what `estimate_weight` ADMITS against, never what
    a 12-row warm tail is charged (21)."""

    def __init__(self, venue: Venue) -> None:
        self._v = venue
        self.weight = 0.0
        self.calls: Dict[str, int] = {}
        self.weight_by: Dict[str, float] = {}   # per-endpoint weight, for instrumentation
        self.pages_by: Dict[str, int] = {}      # pages that came back per paginated endpoint

    def _charge(self, name: str, w: float, pages: int = 0) -> None:
        self.weight += w
        self.calls[name] = self.calls.get(name, 0) + 1
        self.weight_by[name] = self.weight_by.get(name, 0.0) + w
        if pages:
            self.pages_by[name] = self.pages_by.get(name, 0) + pages

    def _paginated_cost(self, req_type: str, rows: Any, page_rows: int) -> "tuple[float, int]":
        """(weight, pages) HL metered for the paginated read that just returned `rows`."""
        meta = getattr(self._v, "last_read", None)
        if isinstance(meta, dict) and meta.get("type") == req_type:
            return float(meta.get("weight") or 0.0), int(meta.get("pages") or 0)
        n = len(rows or [])
        pages = max(1, math.ceil(n / page_rows))
        return float(C.W_INFO * pages + math.ceil(n / C.ITEMS_PER_WEIGHT)), pages

    def portfolio(self, user: str) -> Any:
        self._charge("portfolio", C.W_PORTFOLIO)
        return self._v.portfolio(user)

    def account_state(self, user: str) -> Any:
        self._charge("account_state", C.W_ACCOUNT_STATE)
        return self._v.account_state(user)

    def extras(self, user: str) -> Any:
        self._charge("extras", C.W_EXTRAS)
        return self._v.extras(user)

    def fills(self, user: str, start_ms: int, end_ms: int, aggregate_by_time: Optional[bool] = None,
             max_pages: Optional[int] = None) -> Any:
        # fills_cache passes aggregate_by_time/max_pages only when the signature has them;
        # forward each only when the wrapped venue takes it too.
        kwargs: Dict[str, Any] = {}
        params = _params(self._v.fills)
        if aggregate_by_time is not None and "aggregate_by_time" in params:
            kwargs["aggregate_by_time"] = aggregate_by_time
        if max_pages is not None and "max_pages" in params:
            kwargs["max_pages"] = max_pages
        rows = self._v.fills(user, start_ms, end_ms, **kwargs)
        w, pages = self._paginated_cost("userFillsByTime", rows, C.FILLS_PAGE_ROWS)
        self._charge("fills", w, pages)
        return rows

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Any:
        rows = self._v.candles(coin, interval, start_ms, end_ms)
        if getattr(self._v, "cache_only", False):      # simstage.CacheOnlyVenue: a miss reads nothing from HL
            return rows
        self._charge("candles", C.W_CANDLES + math.ceil(len(rows or []) / 60))
        return rows

    def _funding(self, user: str, start_ms: int, end_ms: int) -> Any:
        rows = self._v.funding(user, start_ms, end_ms)  # type: ignore[attr-defined]
        w, pages = self._paginated_cost("userFunding", rows, C.FUNDING_PAGE_ROWS)
        self._charge("funding", w, pages)
        return rows

    def __getattr__(self, name: str) -> Any:     # max_leverage, leaderboard, ...: uncharged / meta-cached
        # funding is optional on Venue (contracts/venue.py): exposing it here only
        # when the wrapped venue has it keeps hasattr(cv, "funding") == hasattr(v, "funding"),
        # which funding_cache.supports_funding relies on.
        if name == "funding":
            if not callable(getattr(self._v, "funding", None)):
                raise AttributeError(name)
            return self._funding
        return getattr(self._v, name)


@dataclass
class Budget:
    """Weight + wall-clock budget for one stage pass. `clock` is injectable
    so the tests do not sleep."""
    max_weight: float
    max_s: float
    clock: Callable[[], float] = time.monotonic
    spent: float = 0.0
    started: float = field(default=-1.0)

    def __post_init__(self) -> None:
        if self.started < 0:
            self.started = self.clock()

    def allows(self, estimate: float) -> bool:
        if self.clock() - self.started >= self.max_s:
            return False
        return self.spent + estimate <= self.max_weight

    def charge(self, w: float) -> None:
        self.spent += w


def estimate_weight(has_stats: bool, due_full: bool = True) -> float:
    """Pre-flight estimate for Budget.allows(); the real charge comes from
    CountingVenue after the fact (this is pacing, not billing).

    A cold wallet (no stats yet) always pays the full set with a loose
    worst-case fills/funding allowance (3x the per-page estimate: a rough
    upper bound regardless of density now that MAX_FILLS_PAGES_PER_WALLET
    caps the real cost). A warm wallet due for its slow-cadence full
    refresh pays the same full set with a 1-page tail. A warm wallet NOT
    due only pays portfolio + a 1-page fills tail -- the cheap path this
    exists for."""
    if not has_stats:
        fills = C.W_FILLS_PAGE * 3
        funding = C.W_FUNDING_PAGE * 3
        return C.W_PORTFOLIO + C.W_ACCOUNT_STATE + C.W_EXTRAS + fills + funding
    if due_full:
        return C.W_PORTFOLIO + C.W_ACCOUNT_STATE + C.W_EXTRAS + C.W_FILLS_PAGE + C.W_FUNDING_PAGE
    return C.W_PORTFOLIO + C.W_FILLS_PAGE


def _due_full_estimate(meta: Dict[str, Any], now_ms: int) -> bool:
    """Admission-time guess at whether a warm wallet's slow-cadence set is
    due: cadence only (a brand-new fill arriving is only known once the
    fills tail has actually been synced, inside build_wallet)."""
    full_ms = int(meta.get("full_ms") or 0)
    return (now_ms - full_ms) >= C.FULL_REFRESH_EVERY_S * 1000


def order_wallets(addresses: Sequence[str], index: Dict[str, Dict[str, Any]], book: Sequence[str],
                  requested: Sequence[str], now_ms: int) -> List[str]:
    """Book first, then on-demand requests, then stalest first (ties, e.g.
    every never-built wallet, keep the caller's order: best 30d PnL first). Wallets
    sitting out a failure cycle (skip_until_ms in the future) are left out."""
    book_set, req_set = set(book), set(requested)
    rank = {a: i for i, a in reversed(list(enumerate(addresses)))}   # caller's order (universe: 30d PnL desc)

    def key(a: str):
        i = index.get(a) or {}
        tier = 0 if a in book_set else (1 if a in req_set else 2)
        return (tier, int(i.get("updated_ms") or 0), rank[a])

    out = []
    for a in sorted(set(addresses), key=key):
        if int((index.get(a) or {}).get("skip_until_ms") or 0) > now_ms:
            continue
        out.append(a)
    return out


def compute_stats(portfolio: Any, fills: List[Dict[str, Any]], now_ms: int,
                  funding: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Every portfolio and fills metric for one wallet, as JSON-ready dicts."""
    port = M.parse_portfolio(portfolio)
    risk = {}
    for name, win in (("week", PnlWindow.week), ("month", PnlWindow.month), ("allTime", PnlWindow.all_time)):
        w = port.get(name) or {}
        risk[win.value] = M.risk_stats(win, w.get("pnl") or [], w.get("av") or []).model_dump(mode="json")
    trips = M.round_trips(fills, funding)
    trades = {w.value: M.trade_stats(w, trips, fills, now_ms).model_dump(mode="json")
              for w in (PnlWindow.week, PnlWindow.month)}
    t30 = trades["30d"]
    style = M.classify_style(t30["opens_per_day"], t30["median_hold_h"], t30["trips"])
    ws30 = now_ms - C.WINDOW_DAYS * C.DAY_MS
    fills30 = [f for f in fills if int(f["time_ms"]) >= ws30]
    trips30 = [t for t in trips if t.opened_ms >= ws30]
    coins = M.coin_stats(fills30, trips30)
    calendar = M.daily_pnl(port, now_ms)
    month = port.get("month") or {}
    flags: List[str] = []
    if M.fills_truncated(fills30, ws30):
        flags.append("fills_truncated")
    if style is not None and style.value == "algo":
        flags.append("hft")
    perp, other = M.positions.split_perp(fills30)
    if other:
        flags.append("non_perp_ignored")
    if funding is None:
        flags.append("funding_unavailable")   # a failed userFunding read: trips net 0 funding, not fabricated
    liq_count, liq_last_ms = M.real_liquidations(fills30)
    return {
        "risk": risk, "trades": trades, "style": style.value if style else None,
        "coins": [c.model_dump(mode="json") for c in coins],
        "hip3_share": round(M.hip3_share(coins), 6),
        "last_fill_ms": M.last_fill_ms(fills),
        "fills_30d": len(fills30),
        # v13 (user_consensus P0 #3): the wallet's OWN real liquidations, 30d window,
        # distinct from the copy-sim's sim_liquidations.
        "liquidations_30d": liq_count,
        "last_liquidation_ms": liq_last_ms,
        "calendar": [p.model_dump(mode="json") for p in calendar],
        "longest_win_streak_days": M.longest_win_streak_days(calendar),
        "recent_trips": [t.model_dump(mode="json") for t in trips[-C.RECENT_MAX:]][::-1],
        "pnl_spark_30d": [p.model_dump(mode="json")
                          for p in M.downsample(M.curve(month.get("pnl") or []), C.SPARK_MAX_POINTS)],
        "flags": flags,
    }


_CARRIED_FLAGS = ("extras_unavailable", "funding_unavailable")   # only ever known from a full pass


def build_wallet(conn: sqlite3.Connection, venue: CountingVenue, address: str, now_ms: int,
                 source_if_new: Optional[str] = None) -> None:
    """Stage B for one wallet. Raises on any failed read (caller records it).

    Cheap warm path: a wallet whose stats are already on disk gets only
    `portfolio` (the PnL curve) and the fills tail (capped, never re-paging
    what is already covered) MOST passes. `account_state`, `extras`,
    `userFunding` and the one-time liquidation backfill move to
    `config.FULL_REFRESH_EVERY_S` (default 6h) -- UNLESS a new fill just
    landed (the fills sync's newest timestamp moved past what was cached
    before this call: the account genuinely changed) or this is the
    wallet's first-ever build, either of which runs the full set right
    away. `scout_stats.full_ms` tracks the last time the full set ran.

    On a cheap pass, `account_json`/`positions_json`/`positions_ms` are
    carried over UNCHANGED from the last full pass (store.save_stats'
    positions_as_of_ms/full_ms params): they were not asked for this pass,
    not just cheaper to get. `extras_unavailable`/`funding_unavailable`
    (only ever discovered on a full pass) carry over the same way so a
    wallet whose extras/funding reads have been failing doesn't silently
    look fine on a cheap pass in between."""
    prior = store.stats_row(conn, address)
    has_stats = bool(prior and prior.get("updated_ms"))
    full_ms = int((prior or {}).get("full_ms") or 0)

    portfolio = venue.portfolio(address)
    if portfolio is None:
        raise RuntimeError("portfolio read failed")

    prev_newest = fills_cache.newest_fill_ms(conn, address)
    fills = fills_cache.sync_fills(conn, venue, address, C.WINDOW_DAYS, now_ms,   # type: ignore[arg-type]
                                   discovery_config.CACHE_FRESH_S, max_pages=C.MAX_FILLS_PAGES_PER_WALLET)
    new_newest = fills_cache.newest_fill_ms(conn, address)
    got_new_fills = new_newest is not None and (prev_newest is None or new_newest > prev_newest)
    due_full = (not has_stats) or got_new_fills or (now_ms - full_ms >= C.FULL_REFRESH_EVERY_S * 1000)

    state: Optional[Dict[str, Any]] = None
    extras: Optional[Dict[str, Any]] = None
    funding: Optional[List[Dict[str, Any]]] = None
    if due_full:
        state = venue.account_state(address)
        if state is None:
            raise RuntimeError("account_state read failed")
        extras = venue.extras(address)        # optional: None leaves spot-other / staked at 0
        try:
            # One-time per wallet, no-op once done (fills_coverage.liq_backfilled): a wallet synced
            # before the `liquidation` column existed has every cached fill's flag hard-0 regardless
            # of HL's real value. Never blocks the build on failure, same as extras/funding.
            fills_cache.ensure_liquidation_backfilled(conn, venue, address)   # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("scout stage B: %s liquidation backfill failed, will retry next cycle: %s", address, exc)
        try:
            funding = funding_cache.sync_funding(conn, venue, address, C.WINDOW_DAYS, now_ms,   # type: ignore[arg-type]
                                                 discovery_config.CACHE_FRESH_S)
        except funding_cache.FundingFetchError as exc:
            # optional, like extras: a failed userFunding read must not block building the rest
            # of the wallet's stats, it just nets every trip's funding at 0 this pass (flagged).
            logger.warning("scout stage B: %s funding read failed, netting 0: %s", address, exc)
            funding = None
        full_ms = now_ms
    else:
        funding = funding_cache.cached_window(conn, address, C.WINDOW_DAYS, now_ms)   # type: ignore[arg-type]

    stats = compute_stats(portfolio, fills, now_ms, funding)
    if fills_cache.is_lagging(conn, address, now_ms) and "fills_truncated" not in stats["flags"]:
        stats["flags"] = sorted(set(stats["flags"]) | {"fills_truncated"})

    prior_stats = json.loads(prior["stats_json"]) if prior and prior.get("stats_json") else {}
    if due_full:
        if extras is None:
            stats["flags"] = sorted(set(stats["flags"]) | {"extras_unavailable"})
        views = M.position_views(state.get("raw_positions") or {})
        acct = M.account_risk(state, extras, views).model_dump(mode="json")
        account = {"risk": acct, "lev_by_coin": {c: float(p.get("lev") or 0) for c, p in
                                                 (state.get("positions") or {}).items()},
                   "equity_perp_usd": float(state.get("equity_perp_usd") or 0.0),
                   "spot_usdc": float(state.get("spot_usdc") or 0.0)}
        positions_payload = [v.model_dump(mode="json") for v in views]
        positions_as_of_ms = now_ms
    else:
        for carried in _CARRIED_FLAGS:
            if carried in (prior_stats.get("flags") or []) and carried not in stats["flags"]:
                stats["flags"] = sorted(set(stats["flags"]) | {carried})
        account = json.loads(prior["account_json"]) if prior and prior.get("account_json") else {}
        positions_payload = json.loads(prior["positions_json"]) if prior and prior.get("positions_json") else []
        positions_as_of_ms = int((prior or {}).get("positions_ms") or (prior or {}).get("updated_ms") or now_ms)

    store.save_stats(conn, address, now_ms, portfolio, account, positions_payload, stats,
                     positions_as_of_ms=positions_as_of_ms, full_ms=full_ms)
    existing = store.universe_row(conn, address)
    # A wallet the leaderboard does not feed (on-demand file, hand-added custom wallet) gets
    # its universe row, and every later rebuild its fresh account value and window PnL,
    # from its own portfolio. Before this, such a row was written once and never updated.
    # account.get("equity_perp_usd")/.get("spot_usdc"), not `state`: on a cheap pass `state`
    # is None, `account` is either fresh (due_full) or the carried-over last full read.
    if (source_if_new and existing is None) or (existing is not None and existing.get("source") in ("ondemand", "custom")):
        port = M.parse_portfolio(portfolio)
        row: Dict[str, Any] = {"address": address, "display_name": (existing or {}).get("display_name"),
                               "is_vault": int((existing or {}).get("is_vault") or 0),
                               "source": (existing or {}).get("source") or source_if_new,
                               "seen_ms": now_ms,
                               "account_value": float(account.get("equity_perp_usd") or 0.0)
                               + float(account.get("spot_usdc") or 0.0)}
        for name, suf in (("day", "1d"), ("week", "7d"), ("month", "30d"), ("allTime", "all")):
            pnl, roi, vlm = M.window_perf_from_portfolio(port, name)
            row.update({f"pnl_{suf}": pnl, f"roi_{suf}": roi, f"vlm_{suf}": vlm})
        store.upsert_universe(conn, row)


@dataclass
class WalletCost:
    """Per-wallet instrumentation for one stage-B pass (indexing tightening)."""
    address: str
    weight: float
    seconds: float
    pages: float          # fills + funding pages that came back (CountingVenue.pages_by)
    due_full: bool
    calls: Dict[str, int] = field(default_factory=dict)
    failed: bool = False  # the build raised: its weight was burned, it is not a built wallet


@dataclass
class StageResult:
    done: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    weight: float = 0.0
    costs: List[WalletCost] = field(default_factory=list)


def _percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile (numpy's default 'linear' method) --
    no extra dependency for a handful of numbers once per pass."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def bucket_waited_s() -> float:
    """Seconds this process has spent waiting for HL budget so far (acquire
    sleeps and 429 back-offs, hl.rate_limit.waited_s). 0 without hl."""
    return float(_hl_rate_limit.waited_s()) if _hl_rate_limit is not None else 0.0


def summarize_pass(costs: Sequence[WalletCost], bucket_wait_s: float = 0.0) -> Optional[Dict[str, Any]]:
    """p50/p95 weight, pages, seconds + the 5 most expensive wallets, for
    the INFO log line and scout_meta["stage_b_summary"]. None for an empty
    pass (nothing admitted: fully budget-starved or an empty cohort).
    `bucket_wait_s`: how much of the pass was spent asleep waiting for HL
    budget, so a reader (stats_budget_check.py check 2) can tell slow work
    from a pass queued behind the engine on the shared bucket.
    The percentiles are over BUILT wallets (`built`); a failed build
    (`failed`, WalletCost.failed) burned its weight before the read that gave
    up and is neither a cold nor a warm build: 8 of 20 cold builds failed on
    2026-10-15 beside the live scout and their small burned weights pulled the
    cold median to 258 while their rebuilds pushed the warm median to 412.
    `top5` is over every attempt, burned weight included.
    `warm_weight_p50` / `full_weight_p50` split the built median by path:
    the wallets that skipped the slow-cadence set and the ones that took it.
    How many take the full set in a warm pass is how many traded (or failed)
    during the previous pass, a function of that pass's length and so of
    bucket contention, not of the warm path; the all-wallet median flips to a
    full-set wallet once more than half did (11/20 on 2026-10-15, p50 117
    with the warm path itself at about 40). None when no wallet took that
    path."""
    if not costs:
        return None
    built = [c for c in costs if not c.failed]
    weights = [c.weight for c in built]
    warm = [c.weight for c in built if not c.due_full]
    full = [c.weight for c in built if c.due_full]
    pages = [c.pages for c in built]
    seconds = [c.seconds for c in built]
    top5 = sorted(costs, key=lambda c: c.weight, reverse=True)[:5]
    return {
        "n": len(costs),
        "built": len(built),
        "full_count": len(full),
        "failed": len(costs) - len(built),
        "weight_p50": round(_percentile(weights, 0.50), 1),
        "weight_p95": round(_percentile(weights, 0.95), 1),
        "warm_weight_p50": round(_percentile(warm, 0.50), 1) if warm else None,
        "full_weight_p50": round(_percentile(full, 0.50), 1) if full else None,
        "pages_p50": round(_percentile(pages, 0.50), 2),
        "pages_p95": round(_percentile(pages, 0.95), 2),
        "seconds_p50": round(_percentile(seconds, 0.50), 3),
        "seconds_p95": round(_percentile(seconds, 0.95), 3),
        "bucket_wait_s": round(max(0.0, float(bucket_wait_s)), 3),
        "top5": [{"address": c.address, "weight": round(c.weight, 1)} for c in top5],
    }


def run_stage_b(conn: sqlite3.Connection, venue: Venue, addresses: Sequence[str], now_ms: int, budget: Budget,
                book: Sequence[str] = (), requested: Sequence[str] = (), limit: Optional[int] = None,
                progress: Optional[Callable[[int, int], None]] = None,
                clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                custom: Sequence[str] = ()) -> StageResult:
    index = store.stats_index(conn)
    order = order_wallets(addresses, index, list(book) + list(custom), requested, now_ms)   # custom: book priority
    if limit is not None:
        order = order[:limit]
    res = StageResult()
    book_set, req_set, custom_set = set(book), set(requested), set(custom)
    waited_before = bucket_waited_s()
    for i, a in enumerate(order):
        meta = index.get(a) or {}
        has_stats = bool(meta.get("updated_ms"))
        est = estimate_weight(has_stats, _due_full_estimate(meta, now_ms) if has_stats else True)
        if not budget.allows(est):
            res.deferred = order[i:]
            logger.info("scout stage B: budget reached (%.0f weight), %d wallets deferred", budget.spent,
                        len(res.deferred))
            break
        cv = CountingVenue(venue)
        t = clock_ms()
        t0 = time.monotonic()
        failed = False
        try:
            src = "book" if a in book_set else ("custom" if a in custom_set else ("ondemand" if a in req_set else None))
            build_wallet(conn, cv, a, t, source_if_new=src)
            res.done.append(a)
        except Exception as exc:
            n = store.record_stats_failure(conn, a, t, f"{type(exc).__name__}: {exc}", int(C.STAGE_B_EVERY_S * 1000))
            logger.warning("scout stage B: %s failed (%d in a row): %s", a, n, exc)
            res.failed.append(a)
            failed = True
        elapsed = time.monotonic() - t0
        budget.charge(cv.weight)
        res.weight += cv.weight
        pages = float(cv.pages_by.get("fills", 0) + cv.pages_by.get("funding", 0))
        cost = WalletCost(address=a, weight=cv.weight, seconds=elapsed, pages=pages,
                          due_full="account_state" in cv.calls, calls=dict(cv.calls), failed=failed)
        res.costs.append(cost)
        logger.debug("scout stage B wallet %s: weight=%.0f %s pages=%.1f seconds=%.2f full=%s",
                    a, cv.weight, cv.weight_by, pages, elapsed, cost.due_full)
        if progress:
            progress(i + 1, len(order))
    summary = summarize_pass(res.costs, bucket_wait_s=bucket_waited_s() - waited_before)
    if summary:
        logger.info("scout stage B summary: n=%d built=%d full=%d failed=%d weight p50=%.0f p95=%.0f (warm path "
                   "p50=%s, full set p50=%s) pages p50=%.1f p95=%.1f seconds p50=%.2f p95=%.2f bucket wait=%.0fs "
                   "top5=%s",
                   summary["n"], summary["built"], summary["full_count"], summary["failed"], summary["weight_p50"],
                   summary["weight_p95"], summary["warm_weight_p50"], summary["full_weight_p50"],
                   summary["pages_p50"], summary["pages_p95"], summary["seconds_p50"], summary["seconds_p95"],
                   summary["bucket_wait_s"], summary["top5"])
        store.meta_set(conn, {"stage_b_summary": summary})
    return res
