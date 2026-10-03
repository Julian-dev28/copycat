"""HlVenue: the one class that implements contracts.venue.Venue for real.

Every method follows the two rules in contracts/venue.py's module
docstring: a failed read returns None/0.0 (never raises, never looks like
a flat leader or zero equity), and a write without COPYCAT_AGENT_KEY +
COPYCAT_ACCOUNT_ADDRESS returns {ok: False, error} instead of touching the
exchange. See services/hl/README.md for the full contract write-up.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from hyperliquid.utils.error import ServerError
from hyperliquid.utils.signing import OrderType
from hyperliquid.utils.types import Cloid

from . import env, meta, rate_limit, sdk, sizing
from .http import http_post

logger = logging.getLogger(__name__)

LEADERBOARD_HOST = "https://stats-data.hyperliquid.xyz"

# Milliseconds per HL candle interval, used only to estimate an item count
# for the rate limiter's per-60-item candleSnapshot surcharge -- an
# under-estimate just under-charges the bucket slightly, never a
# correctness issue.
_MS_PER_CANDLE: Dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
    "3d": 259_200_000, "1w": 604_800_000,
}


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


def _dexes_to_read(user: str) -> Tuple[List[str], bool]:
    all_dexes = meta.dex_list()
    if os.environ.get("COPYCAT_HL_DEXES") is not None:
        return all_dexes, True
    known = _active_dexes.get(user)
    if known is None or time.time() - _last_full_scan.get(user, 0.0) >= ACTIVE_DEX_RESCAN_S:
        return all_dexes, True
    keep = [d for d in all_dexes if d == "" or d in known]
    return keep, False


def _remember_active(user: str, active: List[str], full_scan: bool, read: List[str]) -> None:
    if full_scan:
        _last_full_scan[user] = time.time()
        _active_dexes[user] = list(active)
    else:
        # Keep dexes we did not read this time; drop ones that went empty.
        prev = _active_dexes.get(user, [])
        _active_dexes[user] = [d for d in prev if d not in read] + list(active)


class HlVenue:
    """Stateless wrapper over hl.http / hl.meta / hl.sdk -- every cache and
    rate limiter lives at module scope in those modules, so instantiating
    this more than once is harmless (and the engine, discovery, and tests
    each do)."""

    # ── reads ────────────────────────────────────────────────────────────

    def account_state(self, user: str) -> Optional[Dict[str, Any]]:
        """{"equity_perp_usd", "spot_usdc", "positions", "available",
        "raw_positions"} -- see contracts.venue.AccountState. None if ANY
        dex's clearinghouseState read (or the spot read) failed; a partial
        read must never look like a flat account or zero equity."""
        try:
            equity = 0.0
            available: Dict[str, float] = {}
            positions: Dict[str, Dict[str, Any]] = {}
            raw_positions: Dict[str, Dict[str, Any]] = {}

            dexes, full_scan = _dexes_to_read(user)
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

            return {
                "equity_perp_usd": equity,
                "spot_usdc": spot_usdc,
                "positions": positions,
                "available": available,
                "raw_positions": raw_positions,
            }
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

    def size_for(self, coin: str, notional_usd: float, mid: float) -> float:
        return sizing.size_for_notional(coin, notional_usd, mid)

    def fills(self, user: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]:
        """userFillsByTime, paginated. HL caps each response at 2000 fills
        and returns them oldest-first within the given window (confirmed
        against mainnet 2026-10-02: 772 fills over a 30d window came back
        strictly nondecreasing by `time`). A full page is paged forward by
        setting the next `startTime` to (that page's last fill time + 1) --
        never by position/offset, which HL's API does not support and
        would re-request the same page forever on a >2000-fill window.

        Stops when a page returns fewer than 2000 fills, or after
        MAX_PAGES (a safety valve against an API that never shrinks below
        the cap). Returns None if any page's fetch failed, or if a page's
        own cursor (last fill's `time`) is unparseable -- pagination
        cannot continue reliably past that point, and a silently truncated
        fill list is worse than a clear failure.
        """
        PAGE_SIZE = 2000
        MAX_PAGES = 50  # 100k-fill ceiling -- far above any realistic window's yield
        out: List[Dict[str, Any]] = []
        cursor = int(start_ms)
        end_ms = int(end_ms)
        for _ in range(MAX_PAGES):
            raw = http_post(
                "/info",
                {"type": "userFillsByTime", "user": user, "startTime": cursor, "endTime": end_ms},
                item_count=PAGE_SIZE,
            )
            if raw is None:
                logger.error(f"[hl.venue] fills: userFillsByTime failed for user={user} startTime={cursor}")
                return None
            if not isinstance(raw, list):
                logger.error(f"[hl.venue] fills: unexpected userFillsByTime response shape for user={user}")
                return None
            for f in raw:
                try:
                    out.append({
                        "time_ms": int(f["time"]),
                        "coin": str(f["coin"]),
                        "px": float(f["px"]),
                        "sz": float(f["sz"]),
                        "side": str(f["side"]),
                        "dir": str(f.get("dir", "")),
                        "start_position": float(f.get("startPosition") or 0),
                        "closed_pnl": float(f.get("closedPnl") or 0),
                        "fee": float(f.get("fee") or 0),
                    })
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(f"[hl.venue] fills: dropping unparseable fill for {user}: {exc}")
            if len(raw) < PAGE_SIZE:
                break
            try:
                last_time = int(raw[-1]["time"])
            except (KeyError, TypeError, ValueError):
                logger.error(f"[hl.venue] fills: page cursor unreadable for user={user}, aborting pagination")
                return None
            cursor = last_time + 1
            if cursor > end_ms:
                break
        return out

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
        url = f"{LEADERBOARD_HOST}/{net_path}/leaderboard"
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
        on success, never None)."""
        ms_per = _MS_PER_CANDLE.get(interval)
        est_count = None
        if ms_per and end_ms > start_ms:
            est_count = min(5000, math.ceil((end_ms - start_ms) / ms_per))
        raw = http_post(
            "/info",
            {"type": "candleSnapshot", "req": {
                "coin": coin, "interval": interval,
                "startTime": int(start_ms), "endTime": int(end_ms),
            }},
            item_count=est_count,
        )
        if not isinstance(raw, list):
            logger.error(f"[hl.venue] candles: candleSnapshot failed for {coin} {interval}")
            return None
        return raw

    # ── writes ───────────────────────────────────────────────────────────

    def set_leverage(self, coin: str, leverage: int, is_cross: bool) -> Dict[str, Any]:
        """Strict: ok is True only when HL's response body says
        status=="ok" -- update_leverage can return HTTP 200 with
        {"status": "err", "response": "<message>"}, and a non-strict
        caller would read that as success. An isolated-only market rejects
        a cross request; we fall back to isolated rather than sending a
        request we know will no-op, and log the fallback (the caller can
        confirm what was actually applied via `is_isolated_only(coin)`).
        """
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}
        if leverage < 1:
            return {"ok": False, "error": f"invalid leverage {leverage} (< 1)"}

        use_cross = bool(is_cross)
        if use_cross and meta.is_isolated_only(coin):
            logger.info(f"[hl.venue] set_leverage: {coin} is isolated-only; cross requested, falling back to isolated")
            use_cross = False

        try:
            exchange = sdk.get_exchange()
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
               max_slippage_pct: float = 1.0) -> Dict[str, Any]:
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
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}
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
            exchange = sdk.get_exchange()
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
        if not parsed.get("ok"):
            logger.warning(
                f"[hl.venue] market {coin} {side} size={send_sz} px={price_str} cloid={cloid} "
                f"not ok: {parsed.get('error')} filled_sz={parsed.get('filled_sz')}"
            )
        return parsed

    def order_status(self, cloid: str) -> Optional[str]:
        """Status of OUR order (COPYCAT_ACCOUNT_ADDRESS) by client order id.

        /info {"type": "orderStatus", "user": ACCOUNT, "oid": "<cloid hex>"}:
        HL accepts either the numeric oid or the 0x cloid string in "oid"
        (the SDK's Info.query_order_by_cloid sends exactly this). Returns
        "filled" | "open" | "canceled" | "rejected" | "triggered" | other
        raw HL status, "unknown" when HL answers unknownOid, None when the
        read failed (no account set, bad cloid, network, bad shape)."""
        account = env.account_address()
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

    def _own_szi(self, coin: str) -> Tuple[Optional[float], Optional[str]]:
        """(signed size, None) of our own live position (0.0 when flat), or
        (None, error) when the read failed."""
        state = self.account_state(env.account_address())
        if state is None:
            return None, "account_state read failed"
        pos = state["raw_positions"].get(coin)
        if pos is None:
            return 0.0, None
        try:
            return float(pos.get("szi") or 0), None
        except (TypeError, ValueError):
            return None, "bad_szi"

    def close(self, coin: str, cloid: Optional[str] = None) -> Dict[str, Any]:
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
        """
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}

        szi, err = self._own_szi(coin)
        if szi is None:
            return {"ok": False, "error": err}
        if szi == 0:
            return {"ok": True, "filled_sz": 0.0}  # already flat

        mid_price = self.mid(coin)
        if mid_price <= 0:
            return {"ok": False, "error": f"invalid price for {coin}"}
        order = self.market(coin, is_buy=szi < 0, size=abs(szi), mid=mid_price,
                            reduce_only=True, cloid=cloid,
                            max_slippage_pct=env.close_max_slippage_pct())

        out: Dict[str, Any] = {k: v for k, v in order.items() if k in ("avg_px", "filled_sz", "ambiguous")}
        after, read_err = self._own_szi(coin)
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
