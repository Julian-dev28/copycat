"""HlVenue: the one class that implements contracts.venue.Venue for real.

Every method follows the two rules in contracts/venue.py's module
docstring: a failed read returns None/0.0 (never raises, never looks like
a flat leader or zero equity), and a write without COPYCAT_AGENT_KEY +
COPYCAT_ACCOUNT_ADDRESS returns {ok: False, error} instead of touching the
exchange. See services/hl/README.md for the full contract write-up.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from hyperliquid.utils.error import ServerError
from hyperliquid.utils.signing import OrderType
from hyperliquid.utils.types import Cloid

from . import env, history, meta, rate_limit, sdk, sizing
from .http import http_post

logger = logging.getLogger(__name__)

LEADERBOARD_HOST = env.STATS_HOST  # default; env.stats_url() resolves the override


def _size_tolerance(sz_dec: Optional[int]) -> float:
    """Half a size tick: a fill this close to the requested size IS the
    requested size (HL reports totalSz as a decimal string at szDecimals)."""
    if sz_dec is None:
        return 1e-9
    return 0.5 * 10.0 ** (-int(sz_dec))


def _order_result(result: Any, requested_sz: Optional[float] = None,
                  sz_dec: Optional[int] = None) -> Dict[str, Any]:
    """Normalize a raw SDK order response into contracts.venue.OrderResult.

    * {"filled": {totalSz, avgPx}}: filled_sz/avg_px always set. ok is True
      only when totalSz >= requested_sz (within half a size tick). An IOC
      that matched part of the size and cancelled the rest is ok False with
      error "partial fill a/b" and the real filled_sz, so the caller books
      exactly what it holds.
    * {"resting": {oid}}: ok True (a GTC that rested; an IOC never rests).
    * {"error": msg} or a non-"ok" top-level status: a clean HL rejection,
      ok False, ambiguous False.
    * "ok" with no statuses at all: HL accepted the request but did not say
      what happened to the order. ok False, ambiguous True.
    """
    if not (isinstance(result, dict) and result.get("status") == "ok"):
        err = result.get("response") if isinstance(result, dict) and "response" in result else result
        return {"ok": False, "error": str(err), "ambiguous": False}
    statuses = (result.get("response") or {}).get("data", {}).get("statuses", [])
    if not statuses or not isinstance(statuses[0], dict):
        return {"ok": False, "error": f"no order status in response: {result}", "ambiguous": True}
    st = statuses[0]
    if st.get("filled"):
        f = st["filled"]
        out: Dict[str, Any] = {"ok": False, "ambiguous": False}
        try:
            out["filled_sz"] = float(f["totalSz"])
            if "avgPx" in f:
                out["avg_px"] = float(f["avgPx"])
            if f.get("oid") is not None:
                out["oid"] = f["oid"]
        except (KeyError, TypeError, ValueError):
            # HL said "filled" but we cannot read how much. Unknown size is
            # exactly the ambiguous case: resolve with a fresh account read.
            return {"ok": False, "error": f"unreadable fill: {f}", "ambiguous": True}
        if requested_sz is None or out["filled_sz"] >= requested_sz - _size_tolerance(sz_dec):
            out["ok"] = True
        else:
            out["error"] = f"partial fill {out['filled_sz']:g}/{requested_sz:g}"
        return out
    if st.get("resting"):
        return {"ok": True, "ambiguous": False, "filled_sz": 0.0}
    if st.get("error"):
        return {"ok": False, "error": str(st["error"]), "ambiguous": False}
    return {"ok": False, "error": f"unrecognized order status: {st}", "ambiguous": True}


# Exceptions from the /exchange POST that mean "the request may have
# reached HL": a read timeout after the bytes went out, a dropped
# connection, a 5xx from a proxy in front of HL. Treated conservatively:
# even a connect timeout (which in practice was never sent) is ambiguous,
# because the price of a wrong "not sent" is a duplicate order, and the
# price of a wrong "maybe sent" is one order_status read.
_AMBIGUOUS_EXC = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    TimeoutError,
    ConnectionError,
    ServerError,
)


def _is_ambiguous_exc(exc: BaseException) -> bool:
    return isinstance(exc, _AMBIGUOUS_EXC)


def _l2_touch(coin: str, is_buy: bool) -> Optional[float]:
    """Best ask (buy) or best bid (sell) from a fresh l2Book read, or None
    if the read failed or that side is empty."""
    raw = http_post("/info", {"type": "l2Book", "coin": coin})
    try:
        levels = (raw or {}).get("levels") or []
        side = levels[1] if is_buy else levels[0]
        if side:
            px = float(side[0]["px"])
            return px if px > 0 else None
    except Exception as exc:
        logger.warning(f"[hl.venue] l2Book lookup failed for {coin}: {exc}")
    return None


def _depth_within(levels: Any, is_buy: bool, max_slippage_pct: float) -> Optional[float]:
    """USD notional (sum px*sz) resting on the side a taker of `is_buy`
    would hit -- asks for a buy, bids for a sell -- at levels within
    mid*(1 + pct/100) (buy) or mid*(1 - pct/100) (sell), bound inclusive.
    mid = (best bid + best ask) / 2 from the same book, so both sides must
    be non-empty. None on bad input; 0.0 is a real "nothing in the band"."""
    if max_slippage_pct is None or max_slippage_pct < 0:
        return None
    try:
        bids, asks = levels[0], levels[1]
        if not bids or not asks:
            return None
        best_bid, best_ask = float(bids[0]["px"]), float(asks[0]["px"])
        if best_bid <= 0 or best_ask <= 0:
            return None
        mid = (best_bid + best_ask) / 2
        side = asks if is_buy else bids
        bound = mid * (1 + max_slippage_pct / 100) if is_buy else mid * (1 - max_slippage_pct / 100)
        total = 0.0
        for lvl in side:
            px, sz = float(lvl["px"]), float(lvl["sz"])
            if (px > bound) if is_buy else (px < bound):
                break   # sides are sorted best-first; everything after is further out
            total += px * sz
        return total
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        logger.warning(f"[hl.venue] depth math failed on malformed book: {exc}")
        return None


def _ioc_limit(coin: str, is_buy: bool, mid_price: float, sz_dec: int,
               max_slippage_pct: float) -> Tuple[Optional[str], Optional[str]]:
    """(price_str, None) for an IOC limit capped at
    mid * (1 +/- max_slippage_pct/100), or (None, "slippage cap") when the
    live touch is already past that cap, so the order is never sent.

    The limit IS the cap: an IOC fills at resting prices, so the cap is the
    worst price we accept, not the price we pay. Rounding goes INSIDE the cap
    (buy down, sell up) so the rounded limit never exceeds it; the touch is
    a valid tick-aligned price at or inside the cap, so rounding inward can
    never cross back over it (re-checked below anyway).

    With no l2Book (read failed or empty side) the order still goes out at
    the cap: HL will match what it can within it, and the cap still bounds
    the worst fill.
    """
    s = max_slippage_pct / 100.0
    cap = mid_price * (1 + s) if is_buy else mid_price * (1 - s)
    if cap <= 0:
        return None, "slippage cap"
    touch = _l2_touch(coin, is_buy)
    if touch is not None and ((is_buy and touch > cap) or (not is_buy and touch < cap)):
        logger.warning(
            f"[hl.venue] {coin} {'BUY' if is_buy else 'SELL'}: touch {touch} past "
            f"{max_slippage_pct:g}% cap {cap:.8g} from mid {mid_price} -- not sending"
        )
        return None, "slippage cap"
    price_str = sizing.round_price(cap, sz_dec, is_perp=True, is_buy=not is_buy)
    px = float(price_str)
    if px <= 0 or (touch is not None and ((is_buy and px < touch) or (not is_buy and px > touch))):
        return None, "slippage cap"
    return price_str, None


# HL orderStatus "status" values (docs: info endpoint, "Query order status
# by oid or cloid"), collapsed to the contract's small set. Every
# "...Canceled" (marginCanceled, reduceOnlyCanceled, selfTradeCanceled,
# siblingFilledCanceled, ...) and "scheduledCancel" -> "canceled"; every
# "...Rejected" (tickRejected, minTradeNtlRejected, perpMarginRejected,
# iocCancelRejected, ...) -> "rejected". "open", "filled", "triggered" pass
# through. An IOC that matched PART of its size and cancelled the rest
# reports "canceled", so "canceled" does not mean zero fill.
def _normalize_order_status(raw: str) -> str:
    if raw in ("open", "filled", "triggered"):
        return raw
    if raw.endswith("Canceled") or raw in ("canceled", "scheduledCancel"):
        return "canceled"
    if raw.endswith("Rejected") or raw == "rejected":
        return "rejected"
    return raw


# ── per-user active-dex cache ───────────────────────────────────────────────
# Reading every user on all ~11 perp dexes every cycle cost 110+ calls and
# ~20s per cycle for 10 leaders. Most wallets only use main (and maybe xyz).
# So: a FULL scan of every dex per user every ACTIVE_DEX_RESCAN_S, and in
# between only main + the dexes where that user held equity or a position at
# the last read. A dex with a position is always re-read, so exits are never
# missed; a brand-new position on a dex the user had never touched is seen
# within ACTIVE_DEX_RESCAN_S. Set COPYCAT_HL_DEXES to pin the set instead.
ACTIVE_DEX_RESCAN_S = float(os.environ.get("COPYCAT_HL_DEX_RESCAN_S", "300"))
_active_dexes: Dict[str, List[str]] = {}
_last_full_scan: Dict[str, float] = {}


def _dexes_to_read(user: str, also: Optional[List[str]] = None) -> Tuple[List[str], bool]:
    """(dexes to read, full scan). `also`: dexes the caller needs read this time
    whatever the cache says (audit B1: the engine passes every dex it holds,
    has pending or may open a copy on, so a HIP-3 copy is never invisible to
    our own read between full scans). Unknown names are dropped."""
    all_dexes = meta.dex_list()
    if os.environ.get("COPYCAT_HL_DEXES") is not None:
        return all_dexes, True
    known = _active_dexes.get(user)
    if known is None or time.time() - _last_full_scan.get(user, 0.0) >= ACTIVE_DEX_RESCAN_S:
        return all_dexes, True
    want = set(also or ())
    keep = [d for d in all_dexes if d == "" or d in known or d in want]
    return keep, False


def note_active_dex(user: str, dex: str) -> None:
    """A write just changed `user`'s position on `dex`: read that dex on every
    later account_state until a full scan finds it empty (audit B1)."""
    known = _active_dexes.get(user)
    if known is not None and dex not in known:
        known.append(dex)


def _remember_active(user: str, active: List[str], full_scan: bool, read: List[str]) -> None:
    if full_scan:
        _last_full_scan[user] = time.time()
        _active_dexes[user] = list(active)
    else:
        # Keep dexes we did not read this time; drop ones that went empty.
        prev = _active_dexes.get(user, [])
        _active_dexes[user] = [d for d in prev if d not in read] + list(active)


# ── per-user account abstraction cache ──────────────────────────────────────
# /info {"type": "userAbstraction", "user": U} returns a bare JSON string
# (curled 2026-10-04: 0xe282...df29 -> "unifiedAccount", 0x2c2e...6985 ->
# "disabled"). Other values per HL docs/SDK: "portfolioMargin", "default",
# "dexAbstraction". It changes only when the user flips it in the UI, so it
# is cached ABSTRACTION_TTL_S per user. A failed read serves the last value
# seen (if any) and is retried next call; with no value at all the key is
# omitted from account_state, never failing the whole read.
ABSTRACTION_TTL_S = float(os.environ.get("COPYCAT_HL_ABSTRACTION_TTL_S", "600"))
UNIFIED_ABSTRACTIONS = frozenset({"unifiedAccount", "portfolioMargin"})
_abstraction: Dict[str, Tuple[str, float]] = {}


def _user_abstraction(user: str) -> Optional[str]:
    key = user.lower()
    cached = _abstraction.get(key)
    if cached is not None and time.time() - cached[1] < ABSTRACTION_TTL_S:
        return cached[0]
    raw = http_post("/info", {"type": "userAbstraction", "user": user})
    if isinstance(raw, str) and raw:
        _abstraction[key] = (raw, time.time())
        return raw
    logger.warning(f"[hl.venue] userAbstraction read failed for {user}: {raw!r}"
                   + (" -- serving last known value" if cached else " -- omitting abstraction"))
    return cached[0] if cached else None


def _spot_usdc_free(balances: List[Dict[str, Any]]) -> float:
    """USDC total - hold from spotClearinghouseState: the margin actually
    free under unified/portfolio margin, where one spot balance
    collateralizes every perp dex."""
    free = 0.0
    for b in balances:
        if isinstance(b, dict) and b.get("coin") == "USDC":
            free += float(b.get("total") or 0) - float(b.get("hold") or 0)
    return max(0.0, free)


def _write_guard(creds: Optional[env.Credentials]) -> Optional[Dict[str, Any]]:
    """None when a write may go ahead, else the OrderResult to return instead.
    Without `creds`: the active credentials must exist (legacy callers).
    With pinned `creds` (audit B2): the active account must still be
    `creds.account`; otherwise nothing is sent and the result carries
    `account_changed: True` so the engine can abort the cycle's writes."""
    if creds is None:
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}
        return None
    if not (creds.account and creds.agent_key):
        return {"ok": False, "error": "pinned credentials incomplete", "ambiguous": False}
    changed = env.account_changed(creds)
    if changed:
        logger.error(f"[hl.venue] {changed}")
        return {"ok": False, "error": changed, "ambiguous": False, "account_changed": True}
    return None


def _exchange_for(creds: Optional[env.Credentials]) -> Any:
    return sdk.get_exchange(creds) if creds is not None else sdk.get_exchange()


class HlVenue:
    """Stateless wrapper over hl.http / hl.meta / hl.sdk -- every cache and
    rate limiter lives at module scope in those modules, so instantiating
    this more than once is harmless (and the engine, discovery, and tests
    each do)."""

    # ── reads ────────────────────────────────────────────────────────────

    def account_state(self, user: str,
                      also_dexes: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """{"equity_perp_usd", "spot_usdc", "positions", "available",
        "raw_positions", "dexes_read"} -- see contracts.venue.AccountState.
        None if ANY dex's clearinghouseState read (or the spot read) failed; a
        partial read must never look like a flat account or zero equity.

        `also_dexes`: always read these dexes too (audit B1). `dexes_read` says
        which dexes this read covered: a coin on a dex NOT in it is unknown,
        never "flat"."""
        try:
            equity = 0.0
            available: Dict[str, float] = {}
            positions: Dict[str, Dict[str, Any]] = {}
            raw_positions: Dict[str, Dict[str, Any]] = {}

            dexes, full_scan = _dexes_to_read(user, also_dexes)
            active: List[str] = []
            for dex in dexes:
                st = http_post("/info", {"type": "clearinghouseState", "user": user, "dex": dex})
                if not isinstance(st, dict) or "assetPositions" not in st:
                    logger.error(f"[hl.venue] account_state: clearinghouseState failed for user={user} dex={dex!r}")
                    return None
                margin = st.get("marginSummary") or {}
                try:
                    equity += float(margin.get("accountValue") or 0)
                    available[dex] = float(st.get("withdrawable") or 0)
                except (TypeError, ValueError):
                    logger.error(f"[hl.venue] account_state: unparseable marginSummary for user={user} dex={dex!r}")
                    return None
                if dex == "" or float(margin.get("accountValue") or 0) > 0 or st["assetPositions"]:
                    active.append(dex)
                for ap in st["assetPositions"] or []:
                    pos = ap.get("position") or {}
                    try:
                        szi = float(pos.get("szi") or 0)
                    except (TypeError, ValueError):
                        continue
                    if szi == 0:
                        continue
                    raw_coin = pos.get("coin", "")
                    coin = raw_coin if (not dex or ":" in raw_coin) else f"{dex}:{raw_coin}"
                    lev = pos.get("leverage") or {}
                    positions[coin] = {
                        "szi": szi,
                        "entry_px": float(pos.get("entryPx") or 0),
                        "lev": float(lev.get("value") or 1),
                        "is_cross": lev.get("type") == "cross",
                    }
                    raw_positions[coin] = pos

            _remember_active(user, active, full_scan, dexes)

            spot = http_post("/info", {"type": "spotClearinghouseState", "user": user})
            if not isinstance(spot, dict) or not isinstance(spot.get("balances"), list):
                logger.error(f"[hl.venue] account_state: spotClearinghouseState failed for user={user}")
                return None
            spot_usdc = sum(float(b.get("total") or 0) for b in spot["balances"] if b.get("coin") == "USDC")

            out: Dict[str, Any] = {
                "equity_perp_usd": equity,
                "spot_usdc": spot_usdc,
                "positions": positions,
                "available": available,
                "raw_positions": raw_positions,
                "dexes_read": list(dexes),
            }
            try:
                abstraction = _user_abstraction(user)
            except Exception as exc:  # never fail account_state over this
                logger.warning(f"[hl.venue] account_state: abstraction lookup failed for {user}: {exc}")
                abstraction = None
            if abstraction is not None:
                out["abstraction"] = abstraction
                if abstraction in UNIFIED_ABSTRACTIONS:
                    # Per-dex withdrawable is not meaningful here (measured
                    # live: $5.7k reported vs $844k actually free).
                    try:
                        free = _spot_usdc_free(spot["balances"])
                        out["available"] = {dex: free for dex in available}
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"[hl.venue] account_state: unparseable spot USDC hold for {user}, "
                                       f"keeping per-dex withdrawable: {exc}")
            return out
        except Exception as exc:
            logger.error(f"[hl.venue] account_state: unexpected failure for user={user}: {exc}")
            return None

    def extras(self, user: str) -> Optional[Dict[str, Any]]:
        """{"spot_other_usd", "staked_hype_usd"} -- see contracts.venue.Extras.

        Illiquid-mark guard: one leader showed a $1B "MAX" balance in a spot
        token whose real 24h pair volume was a few thousand dollars --
        `total * midPx` is a real float but not a realizable value. A
        token whose marked value exceeds 10x its own 24h pair notional
        volume (`dayNtlVlm`) counts as 0 toward spot_other_usd instead of
        poisoning the leader's sized equity; the read itself still
        succeeds (this is a per-token exclusion, not a failed read).

        Returns None if the spot balances, the spot price table, or the
        delegator summary read failed -- a partial read must never look
        like a leader with no extra capital.
        """
        try:
            spot = http_post("/info", {"type": "spotClearinghouseState", "user": user})
            if not isinstance(spot, dict) or not isinstance(spot.get("balances"), list):
                logger.error(f"[hl.venue] extras: spotClearinghouseState failed for user={user}")
                return None

            prices = meta.spot_prices()
            if prices is None:
                logger.error(f"[hl.venue] extras: spot price table unavailable for user={user}")
                return None

            deleg = http_post("/info", {"type": "delegatorSummary", "user": user})
            if not isinstance(deleg, dict):
                logger.error(f"[hl.venue] extras: delegatorSummary failed for user={user}")
                return None

            spot_other_usd = 0.0
            for b in spot["balances"]:
                if not isinstance(b, dict):
                    continue
                coin_name = b.get("coin", "")
                if coin_name == "USDC" or not coin_name:
                    continue
                try:
                    total = float(b.get("total") or 0)
                except (TypeError, ValueError):
                    continue
                if total == 0:
                    continue
                priced = prices.get(coin_name)
                if priced is None:
                    logger.debug(f"[hl.venue] extras: {user} no USDC spot price for {coin_name!r} -- valued at 0")
                    continue
                px, day_ntl_vlm = priced
                value = total * px
                if day_ntl_vlm <= 0 or value > 10 * day_ntl_vlm:
                    logger.warning(
                        f"[hl.venue] extras: {user} {coin_name} marked ${value:,.0f} vs 24h pair "
                        f"volume ${day_ntl_vlm:,.0f} -- illiquid mark, counting as 0"
                    )
                    continue
                spot_other_usd += value

            try:
                delegated = float(deleg.get("delegated") or 0)
                undelegated = float(deleg.get("undelegated") or 0)
                pending = float(deleg.get("totalPendingWithdrawal") or 0)
            except (TypeError, ValueError):
                logger.error(f"[hl.venue] extras: unparseable delegatorSummary for {user}: {deleg}")
                return None
            staked_hype = delegated + undelegated + pending

            hype_priced = prices.get("HYPE")
            if hype_priced is None:
                # HYPE always has a USDC spot market -- a missing price here
                # means the spot price table itself is degraded, not that
                # HYPE is genuinely unpriced. Fail the whole read rather
                # than silently valuing the stake at 0.
                logger.error(f"[hl.venue] extras: no HYPE spot price available for {user}")
                return None
            staked_hype_usd = staked_hype * hype_priced[0]

            return {"spot_other_usd": spot_other_usd, "staked_hype_usd": staked_hype_usd}
        except Exception as exc:
            logger.error(f"[hl.venue] extras: unexpected failure for user={user}: {exc}")
            return None

    def mid(self, coin: str) -> float:
        """Current mid price. HIP-3 namespaced coins (e.g. `xyz:TSLA`) live
        on a separate perpDex and aren't in the bare `allMids` call -- the
        dex is derived from the `coin:` prefix. 0.0 on any failure."""
        dex = coin.split(":", 1)[0] if ":" in coin else ""
        payload: Dict[str, Any] = {"type": "allMids"}
        if dex:
            payload["dex"] = dex
        raw = http_post("/info", payload)
        if not isinstance(raw, dict):
            logger.error(f"[hl.venue] mid: allMids failed for coin={coin!r}")
            return 0.0
        v = raw.get(coin)
        if v is None:
            logger.warning(f"[hl.venue] mid: {coin!r} missing from allMids(dex={dex!r})")
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def max_leverage(self, coin: str) -> int:
        return meta.max_leverage(coin)

    def is_isolated_only(self, coin: str) -> bool:
        return meta.is_isolated_only(coin)

    def market_stats(self, coin: str) -> Optional[Dict[str, Any]]:
        """MarketStats for one coin (contracts.venue.MarketStats): mark_px,
        mid_px, day_volume_usd, open_interest_usd, max_leverage. One
        metaAndAssetCtxs call per dex per ~30s serves every coin on that dex
        (meta.asset_stats). HIP-3 "dex:COIN" reads that dex. None on a failed
        read or a coin not listed there."""
        try:
            dex = coin.split(":", 1)[0] if ":" in coin else ""
            stats = meta.asset_stats(dex)
            if stats is None:
                return None
            s = stats.get(coin)
            if s is None:
                logger.warning(f"[hl.venue] market_stats: {coin!r} not on dex {dex!r}")
                return None
            return dict(s)
        except Exception as exc:
            logger.error(f"[hl.venue] market_stats: unexpected failure for {coin}: {exc}")
            return None

    def depth_usd(self, coin: str, is_buy: bool, max_slippage_pct: float) -> Optional[float]:
        """USD notional fillable on the book within max_slippage_pct of mid:
        ask side for a buy, bid side for a sell (l2Book, weight 2, cached 2s
        per coin). Only sees HL's top 20 levels a side, so a wide band on a
        deep book under-counts. None on a failed read or a one-sided book."""
        try:
            book = meta.l2_book(coin)
            if book is None:
                return None
            return _depth_within(book.get("levels"), is_buy, max_slippage_pct)
        except Exception as exc:
            logger.error(f"[hl.venue] depth_usd: unexpected failure for {coin}: {exc}")
            return None

    def size_for(self, coin: str, notional_usd: float, mid: float) -> float:
        return sizing.size_for_notional(coin, notional_usd, mid)

    def fills(self, user: str, start_ms: int, end_ms: int,
              aggregate_by_time: bool = False) -> Optional[List[Dict[str, Any]]]:
        """userFillsByTime over [start_ms, end_ms] (both inclusive), paginated.

        HL caps each response at 2000 rows and returns them oldest-first
        (confirmed against mainnet 2026-10-02: 772 fills over a 30d window
        came back strictly nondecreasing by `time`).

        aggregate_by_time: pass HL's `aggregateByTime: true`. HL then merges
        every partial fill of ONE order at ONE millisecond (same coin, oid,
        time) into one row. Verified 2026-10-05 on 0xe2823659 over 30d
        (870 raw fills -> 189 rows, 71 of them merged from 2-54 partials),
        every merged row against its raw group:
          sz          = sum of the partials' sz
          px          = size-weighted average px (VWAP)
          closedPnl   = sum;  fee = sum
          startPosition, hash, tid = the FIRST partial's, so
          startPosition + signed sz is still the true end position
          dir         = the FIRST partial's label. A group that flips
                        (Close Short partials then a "Short > Long" one)
                        comes back as "Close Short" with sz 200 from -100:
                        derive open/close/flip from startPosition+side+sz,
                        never from `dir` (discovery.positions already does).
        Spot "Spot Dust Conversion" rows (tid 0) are not returned at all.
        Measured on discovery's candidates: 64,241 -> 10,746 fills.

        Pagination: the next page starts AT the last row's time, not +1, and
        the rows of that last millisecond are dropped from this page and
        taken from the next one. HL cuts a page at 2000 rows even in the
        middle of a millisecond: measured 2026-10-05 on 0xf5d81a13
        (aggregated), page 1 held 39 rows at its last ms and a refetch from
        that ms returned 49, so a `last + 1` cursor silently lost 10. A full
        page whose rows ALL share one millisecond cannot advance that way;
        it falls back to `last + 1` and logs it.

        Stops when a page returns fewer than 2000 rows, or after MAX_PAGES
        (a safety valve against an API that never shrinks below the cap).
        Returns None if any page's fetch failed, or if a page's own cursor
        (last row's `time`) is unparseable: a silently truncated fill list
        is worse than a clear failure.
        """
        PAGE_SIZE = 2000
        MAX_PAGES = 50  # 100k-fill ceiling -- far above any realistic window's yield
        out: List[Dict[str, Any]] = []
        held: List[Dict[str, Any]] = []   # last page's rows at its last ms, re-read by the next page
        cursor = int(start_ms)
        end_ms = int(end_ms)
        for _ in range(MAX_PAGES):
            held = []
            payload: Dict[str, Any] = {"type": "userFillsByTime", "user": user,
                                       "startTime": cursor, "endTime": end_ms}
            if aggregate_by_time:
                payload["aggregateByTime"] = True
            raw = http_post("/info", payload)
            if raw is None:
                logger.error(f"[hl.venue] fills: userFillsByTime failed for user={user} startTime={cursor}")
                return None
            if not isinstance(raw, list):
                logger.error(f"[hl.venue] fills: unexpected userFillsByTime response shape for user={user}")
                return None
            page: List[Dict[str, Any]] = []
            for f in raw:
                try:
                    page.append({
                        "time_ms": int(f["time"]),
                        "coin": str(f["coin"]),
                        "px": float(f["px"]),
                        "sz": float(f["sz"]),
                        "side": str(f["side"]),
                        "dir": str(f.get("dir", "")),
                        "start_position": float(f.get("startPosition") or 0),
                        "closed_pnl": float(f.get("closedPnl") or 0),
                        "fee": float(f.get("fee") or 0),
                        # S7: what the engine needs to book OUR fills exactly
                        "cloid": f.get("cloid") or None,
                        "oid": f.get("oid"),
                        "tid": f.get("tid"),
                        "hash": f.get("hash"),
                        "liquidation": bool(f.get("liquidation")),
                    })
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(f"[hl.venue] fills: dropping unparseable fill for {user}: {exc}")
            if len(raw) < PAGE_SIZE:
                out.extend(page)
                break
            try:
                first_time, last_time = int(raw[0]["time"]), int(raw[-1]["time"])
            except (KeyError, TypeError, ValueError):
                logger.error(f"[hl.venue] fills: page cursor unreadable for user={user}, aborting pagination")
                return None
            if first_time >= last_time:
                logger.warning(f"[hl.venue] fills: {PAGE_SIZE} rows at one millisecond ({last_time}) for "
                               f"user={user}; rows past the cap at that ms are lost")
                out.extend(page)
                cursor = last_time + 1
            else:
                out.extend(f for f in page if f["time_ms"] < last_time)   # the next page re-reads last_time whole
                held = [f for f in page if f["time_ms"] >= last_time]
                cursor = last_time
            if cursor > end_ms:
                break
        else:
            logger.warning(f"[hl.venue] fills: hit MAX_PAGES={MAX_PAGES} for user={user}; "
                           f"result truncated at {cursor}")
        return out + held

    def leaderboard(self) -> Optional[List[Dict[str, Any]]]:
        """GET the public HL leaderboard snapshot for the active network.

        Real response shape (curled 2026-10-02, Mainnet, 46,953 rows):

            {"leaderboardRows": [
              {
                "ethAddress": "0x85ecf584f25db6f146718b86d493e33c5af72052",
                "accountValue": "62330451.1721990108",
                "windowPerformances": [
                  ["day",     {"pnl": "310963.157278",     "roi": "0.0055071207", "vlm": "1450003736.8299999237"}],
                  ["week",    {"pnl": "2852804.9591829996", "roi": "0.0512880601", "vlm": "9048872792.9899978638"}],
                  ["month",   {"pnl": "960491.2623950004",  "roi": "0.014177401",  "vlm": "40991110551.9400100708"}],
                  ["allTime", {"pnl": "5486773.7299610004", "roi": "0.0456111172", "vlm": "218905315448.549987793"}]
                ],
                "prize": 0,
                "displayName": null
              },
              ...
            ]}

        Every numeric value is a STRING, not a number -- callers must
        cast. `windowPerformances` is a list of [label, dict] pairs, not an
        object keyed by label (`dict(row["windowPerformances"])` is the
        idiomatic way to index it). Raw rows, unnormalized -- the discovery
        service owns turning this into `contracts.models.TraderScore`.

        This endpoint lives on a separate host (stats-data.hyperliquid.xyz,
        not api.hyperliquid.xyz) with its own Mainnet/Testnet path segment;
        it still respects COPYCAT_NETWORK rather than hardcoding Mainnet.
        None on any fetch/parse failure.
        """
        net_path = "Testnet" if env.network() == "testnet" else "Mainnet"
        url = f"{env.stats_url()}/{net_path}/leaderboard"
        try:
            resp = requests.get(url, timeout=env.request_timeout_s())
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.error(f"[hl.venue] leaderboard fetch failed: {exc}")
            return None
        rows = body.get("leaderboardRows") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            logger.error("[hl.venue] leaderboard: unexpected response shape")
            return None
        return rows

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]:
        """candleSnapshot. Returns HL's raw candle dicts (t, T, s, i, o, c,
        h, l, v, n) unnormalized. None on failure; an empty list is a
        genuine "no candles in this window" (HL returns a list either way
        on success, never None). The per-60-candle rate surcharge is charged
        by http_post after the response, from the real candle count."""
        raw = http_post(
            "/info",
            {"type": "candleSnapshot", "req": {
                "coin": coin, "interval": interval,
                "startTime": int(start_ms), "endTime": int(end_ms),
            }},
        )
        if not isinstance(raw, list):
            logger.error(f"[hl.venue] candles: candleSnapshot failed for {coin} {interval}")
            return None
        return raw

    def portfolio(self, user: str) -> Optional[List[Any]]:
        """POST /info {"type": "portfolio", "user": U}. Weight 20 (HL's
        default for documented /info types; not in the weight-2 or 60 list).

        Real shape (curled 2026-10-04 for 0xe2823659...df29, trimmed): a
        list of 8 [window, dict] pairs, windows in this order: day, week,
        month, allTime, perpDay, perpWeek, perpMonth, perpAllTime.

            [
              ["day", {
                "accountValueHistory": [[1790975760052, "2420588.4847900001"],
                                        [1790984160003, "2492036.7283669999"], ...],  # 13 points
                "pnlHistory":          [[1790975760052, "0.0"],
                                        [1790984160003, "71448.243577"], ...],
                "vlm": "265999.99"
              }],
              ["week",    {... 63 points ...}],
              ["month",   {... 47 points ...}],
              ["allTime", {"accountValueHistory": [[1741213560044, "0.0"], ...], ...,
                           "vlm": "174791463.2100000083"}],          # 89 points
              ["perpDay", {...}], ["perpWeek", {...}], ["perpMonth", {...}], ["perpAllTime", {...}]
            ]

        Timestamps are int ms; every value (history points and vlm) is a
        STRING. pnlHistory is cumulative from the window start (first point
        "0.0"). The non-perp windows include spot; the perp* ones are
        perp-only. Returned raw; None on a failed read or if the body is not
        a list of [str, dict] pairs.
        """
        try:
            raw = http_post("/info", {"type": "portfolio", "user": user})
            if not isinstance(raw, list) or not all(
                isinstance(p, list) and len(p) == 2 and isinstance(p[0], str) and isinstance(p[1], dict)
                for p in raw
            ):
                logger.error(f"[hl.venue] portfolio: read failed or bad shape for user={user}: "
                             f"{type(raw).__name__}")
                return None
            return raw
        except Exception as exc:
            logger.error(f"[hl.venue] portfolio: unexpected failure for user={user}: {exc}")
            return None

    def open_orders(self, user: str) -> Optional[List[Dict[str, Any]]]:
        """POST /info {"type": "frontendOpenOrders", "user": U, "dex": D} for
        main + every dex the active-dex cache says this user is on (the same
        cache account_state uses; a cold or stale cache means every dex).
        Weight 20 per dex read.

        Row shape (curled 2026-10-04, main dex):
            {"coin": "BTC", "side": "A", "limitPx": "89000.0", "sz": "10.0",
             "oid": 563616501017, "timestamp": 1790954077641,
             "triggerCondition": "N/A", "isTrigger": false, "triggerPx": "0.0",
             "children": [], "isPositionTpsl": false, "reduceOnly": false,
             "orderType": "Limit", "origSz": "10.0", "tif": "Gtc", "cloid": null}

        Rows are raw except `coin`, which is namespaced "dex:COIN" for HIP-3
        dexes (left alone if HL already prefixed it), matching
        account_state's position keys. A dex found holding orders is added
        to the active-dex cache (without resetting the rescan clock), so
        the next incremental read keeps it. None if ANY dex read fails: a
        partial list must never look like "no orders".

        Gap: between full rescans (COPYCAT_HL_DEX_RESCAN_S), an order on a
        dex where the user has no equity, no position, and had no orders at
        the last scan is not seen until the next full rescan.
        """
        try:
            dexes, _full = _dexes_to_read(user)
            out: List[Dict[str, Any]] = []
            with_orders: List[str] = []
            for dex in dexes:
                raw = http_post("/info", {"type": "frontendOpenOrders", "user": user, "dex": dex})
                if not isinstance(raw, list):
                    logger.error(f"[hl.venue] open_orders: frontendOpenOrders failed for user={user} dex={dex!r}")
                    return None
                for o in raw:
                    if not isinstance(o, dict):
                        logger.error(f"[hl.venue] open_orders: non-dict row for user={user} dex={dex!r}")
                        return None
                    row = dict(o)
                    c = str(row.get("coin", ""))
                    row["coin"] = c if (not dex or ":" in c) else f"{dex}:{c}"
                    out.append(row)
                if raw and dex:
                    with_orders.append(dex)
            if with_orders:
                known = _active_dexes.setdefault(user, [])
                known.extend(d for d in with_orders if d not in known)
            return out
        except Exception as exc:
            logger.error(f"[hl.venue] open_orders: unexpected failure for user={user}: {exc}")
            return None

    def ledger_updates(self, user: str, start_ms: int) -> Optional[List[Dict[str, Any]]]:
        """Non-funding ledger rows since start_ms (hl.history.ledger_since).

        Row shapes (curled 2026-10-11 on public addresses), each {time, hash, delta}:
            {"type": "deposit", "usdc": "1964.72"}
            {"type": "withdraw", "usdc": "9999.0", "nonce": ..., "fee": "1.0"}
            {"type": "accountClassTransfer", "usdc": "47000.0", "toPerp": false}
            {"type": "internalTransfer", "usdc": "1.0", "user": S, "destination": D, "fee": "0.3"}
            {"type": "send", "user": S, "destination": D, "sourceDex": "spot",
             "destinationDex": "", "token": "USDC", "amount": "100.0", "usdcValue": "100.0",
             "fee": "0.0", "nativeTokenFee": "0.0", "nonce": ..., "feeToken": ""}
            {"type": "spotTransfer", "token": "USDC", "amount": "1.0", "usdcValue": "1.0",
             "user": S, "destination": D, "fee": "0.0", ...}
            {"type": "vaultDeposit", "vault": V, "usdc": "5000.0"}
            {"type": "vaultWithdraw", "vault": V, "user": U, "requestedUsd": ...,
             "netWithdrawnUsd": "50000.0", ...}
            {"type": "liquidation", ...}, {"type": "spotGenesis", ...}, {"type": "cStakingTransfer", ...}
        None on any failure (never a partial list)."""
        try:
            return history.ledger_since(user, start_ms)
        except Exception as exc:
            logger.error(f"[hl.venue] ledger_updates: unexpected failure for user={user}: {exc}")
            return None

    # ── writes ───────────────────────────────────────────────────────────

    def pin_credentials(self) -> Optional[env.Credentials]:
        """The active write credentials, frozen for one engine cycle (B2)."""
        return env.pin_credentials()

    def set_leverage(self, coin: str, leverage: int, is_cross: bool,
                     creds: Optional[env.Credentials] = None) -> Dict[str, Any]:
        """Strict: ok is True only when HL's response body says
        status=="ok" -- update_leverage can return HTTP 200 with
        {"status": "err", "response": "<message>"}, and a non-strict
        caller would read that as success. An isolated-only market rejects
        a cross request; we fall back to isolated rather than sending a
        request we know will no-op, and log the fallback (the caller can
        confirm what was actually applied via `is_isolated_only(coin)`).
        """
        blocked = _write_guard(creds)
        if blocked:
            return blocked
        if leverage < 1:
            return {"ok": False, "error": f"invalid leverage {leverage} (< 1)"}

        use_cross = bool(is_cross)
        if use_cross and meta.is_isolated_only(coin):
            logger.info(f"[hl.venue] set_leverage: {coin} is isolated-only; cross requested, falling back to isolated")
            use_cross = False

        try:
            exchange = _exchange_for(creds)
            result = exchange.update_leverage(leverage, coin, is_cross=use_cross)
        except Exception as exc:
            logger.error(f"[hl.venue] set_leverage({coin}, is_cross={use_cross}) failed: {exc}")
            return {"ok": False, "error": str(exc)}

        if isinstance(result, dict) and result.get("status") == "ok":
            return {"ok": True}
        err = result.get("response") if isinstance(result, dict) else result
        logger.error(f"[hl.venue] set_leverage({coin}, is_cross={use_cross}) rejected: {err}")
        return {"ok": False, "error": str(err)}

    def market(self, coin: str, is_buy: bool, size: float, mid: float,
               reduce_only: bool = False, cloid: Optional[str] = None,
               max_slippage_pct: float = 1.0,
               creds: Optional[env.Credentials] = None) -> Dict[str, Any]:
        """IOC limit order capped at mid * (1 +/- max_slippage_pct/100).

        * Opens are bumped up to HL's $10.50 floor; reduce_only orders are
          sent at their own size, never bumped (sizing.order_size).
        * If the live touch is already past the cap: ok False, error
          "slippage cap", nothing sent.
        * cloid (0x + 32 hex) is attached as HL's client order id, so an
          ambiguous result can be resolved with order_status(cloid).
        * ok True only on a FULL fill; partial fills return ok False with
          filled_sz/avg_px set. A timeout or dropped connection on the
          /exchange POST returns ambiguous True: the order may be live.
        """
        blocked = _write_guard(creds)
        if blocked:
            return blocked
        if mid <= 0:
            return {"ok": False, "error": f"invalid mid price for {coin}"}
        if not (size > 0):
            return {"ok": False, "error": f"invalid size {size} for {coin}"}
        if not (max_slippage_pct > 0):
            return {"ok": False, "error": f"invalid max_slippage_pct {max_slippage_pct}"}
        hl_cloid = None
        if cloid is not None:
            try:
                hl_cloid = Cloid.from_str(cloid)
            except Exception:
                return {"ok": False, "error": f"invalid cloid {cloid!r} (need 0x + 32 hex)"}

        side = "BUY" if is_buy else "SELL"
        try:
            sz_dec = meta.sz_decimals(coin)
            send_sz = sizing.order_size(size, mid, sz_dec, reduce_only)
            if send_sz <= 0:
                return {"ok": False, "error": f"size {size} rounds to 0 at {sz_dec} decimals"}
            price_str, err = _ioc_limit(coin, is_buy, mid, sz_dec, max_slippage_pct)
            if err:
                return {"ok": False, "error": err, "ambiguous": False}
            exchange = _exchange_for(creds)
        except Exception as exc:
            logger.error(f"[hl.venue] market({coin}) failed before send: {exc}")
            return {"ok": False, "error": str(exc), "ambiguous": False}

        # /exchange counts against the same per-IP budget (weight 1 per
        # unbatched action). Never block an order on our own estimate.
        try:
            rate_limit.HL_LIMITER.acquire(1, max_wait=2.0)
        except Exception as exc:
            logger.warning(f"[hl.venue] limiter charge for /exchange failed, sending anyway: {exc}")

        try:
            result = exchange.order(
                coin, is_buy, send_sz, float(price_str), OrderType(limit={"tif": "Ioc"}),
                reduce_only=reduce_only, cloid=hl_cloid,
            )
        except Exception as exc:
            amb = _is_ambiguous_exc(exc)
            logger.error(
                f"[hl.venue] market {coin} {side} size={send_sz} px={price_str} cloid={cloid} "
                f"raised {type(exc).__name__}: {exc} (ambiguous={amb})"
            )
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "ambiguous": amb}

        parsed = _order_result(result, requested_sz=send_sz, sz_dec=sz_dec)
        if float(parsed.get("filled_sz") or 0.0) > 0 or parsed.get("ambiguous"):
            # our position on this dex may have changed: read it every cycle (B1)
            who = creds.account if creds is not None else env.account_address()
            if who and ":" in coin:
                note_active_dex(who, coin.split(":", 1)[0])
        if not parsed.get("ok"):
            logger.warning(
                f"[hl.venue] market {coin} {side} size={send_sz} px={price_str} cloid={cloid} "
                f"not ok: {parsed.get('error')} filled_sz={parsed.get('filled_sz')}"
            )
        return parsed

    def order_status(self, cloid: str, account: Optional[str] = None) -> Optional[str]:
        """Status of OUR order by client order id. `account`: the account the
        order was sent for (the engine passes its pinned cycle account, B2);
        default the active account.

        /info {"type": "orderStatus", "user": ACCOUNT, "oid": "<cloid hex>"}:
        HL accepts either the numeric oid or the 0x cloid string in "oid"
        (the SDK's Info.query_order_by_cloid sends exactly this). Returns
        "filled" | "open" | "canceled" | "rejected" | "triggered" | other
        raw HL status, "unknown" when HL answers unknownOid, None when the
        read failed (no account set, bad cloid, network, bad shape)."""
        account = account or env.account_address()
        if not account:
            logger.error("[hl.venue] order_status: COPYCAT_ACCOUNT_ADDRESS not set")
            return None
        try:
            Cloid.from_str(cloid)
        except Exception:
            logger.error(f"[hl.venue] order_status: invalid cloid {cloid!r}")
            return None
        raw = http_post("/info", {"type": "orderStatus", "user": account, "oid": cloid})
        if not isinstance(raw, dict):
            logger.error(f"[hl.venue] order_status: read failed for cloid={cloid}")
            return None
        top = raw.get("status")
        if top == "unknownOid":
            return "unknown"
        if top == "order":
            inner = (raw.get("order") or {}).get("status")
            if isinstance(inner, str) and inner:
                return _normalize_order_status(inner)
        logger.error(f"[hl.venue] order_status: unexpected response for cloid={cloid}: {raw}")
        return None

    def _own_szi(self, coin: str, account: Optional[str] = None) -> Tuple[Optional[float], Optional[str]]:
        """(signed size, None) of our own live position (0.0 when flat), or
        (None, error) when the read failed. `account` default: the active one.
        The coin's dex is always read (B1)."""
        dex = coin.split(":", 1)[0] if ":" in coin else ""
        state = self.account_state(account or env.account_address(), also_dexes=[dex] if dex else None)
        if state is None:
            return None, "account_state read failed"
        pos = state["raw_positions"].get(coin)
        if pos is None:
            return 0.0, None
        try:
            return float(pos.get("szi") or 0), None
        except (TypeError, ValueError):
            return None, "bad_szi"

    def close(self, coin: str, cloid: Optional[str] = None,
              creds: Optional[env.Credentials] = None) -> Dict[str, Any]:
        """Reduce-only full close at market (IOC), sized off our OWN live
        position (never a caller-supplied size), then confirmed with a
        FRESH read: ok True only if the position is now flat.

        * Already flat before sending: {ok: True, filled_sz: 0.0}.
        * Still open after the order (partial fill, slippage cap, rejection):
          ok False with the order's error and filled_sz.
        * Post-order read failed: ok False, error says so; the order's own
          fields (filled_sz, ambiguous) are kept.
        Retrying is always safe: every call re-reads the size it closes, and
        reduce_only can never flip the position.

        `creds` (B2): size, order and confirmation all use `creds.account`,
        never the active account re-resolved mid-call; refused (nothing sent)
        once the active account is no longer `creds.account`.
        """
        blocked = _write_guard(creds)
        if blocked:
            return blocked
        account = creds.account if creds is not None else None

        szi, err = self._own_szi(coin, account)
        if szi is None:
            return {"ok": False, "error": err}
        if szi == 0:
            return {"ok": True, "filled_sz": 0.0}  # already flat

        mid_price = self.mid(coin)
        if mid_price <= 0:
            return {"ok": False, "error": f"invalid price for {coin}"}
        order = self.market(coin, is_buy=szi < 0, size=abs(szi), mid=mid_price,
                            reduce_only=True, cloid=cloid,
                            max_slippage_pct=env.close_max_slippage_pct(), creds=creds)
        if order.get("account_changed"):
            return order

        out: Dict[str, Any] = {k: v for k, v in order.items()
                               if k in ("avg_px", "filled_sz", "ambiguous", "oid")}
        after, read_err = self._own_szi(coin, account)
        if after is None:
            out.update(ok=False, error=f"close sent ({order.get('error') or 'ok'}) but post-close read failed: {read_err}")
            return out
        if after == 0:
            out["ok"] = True
            out.pop("ambiguous", None)   # the fresh read resolved it: flat
            out.setdefault("filled_sz", abs(szi))
            return out
        out.update(ok=False, error=order.get("error") or f"position not flat after close: szi {after:g}")
        out.setdefault("filled_sz", 0.0)
        return out
