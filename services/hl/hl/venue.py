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
import math
from typing import Any, Dict, List, Optional, Tuple

import requests
from hyperliquid.utils.signing import OrderType

from . import env, meta, sdk, sizing
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


def _order_result(result: Any) -> Dict[str, Any]:
    """Normalize a raw SDK order/leverage response into the OrderResult
    shape {ok, error?, avg_px?, filled_sz?}."""
    if not (isinstance(result, dict) and result.get("status") == "ok"):
        return {"ok": False, "error": str(result)}
    statuses = result.get("response", {}).get("data", {}).get("statuses", [])
    if statuses:
        st = statuses[0]
        if st.get("filled"):
            f = st["filled"]
            out: Dict[str, Any] = {"ok": True}
            try:
                if "avgPx" in f:
                    out["avg_px"] = float(f["avgPx"])
                if "totalSz" in f:
                    out["filled_sz"] = float(f["totalSz"])
            except (TypeError, ValueError):
                pass
            return out
        if st.get("error"):
            return {"ok": False, "error": st["error"]}
    return {"ok": True}


def _ioc_cross_price(coin: str, is_buy: bool, mid_price: float) -> float:
    """Limit price for an IOC order that reliably crosses the live book.

    Anchors to the current best bid/ask from a fresh L2 read and steps 1%
    past the touch. An IOC fills at the resting price, so that 1% is
    headroom absorbing price movement between this read and the order
    landing, not real slippage paid. Falls back to mid +/- 1% if the L2
    read fails.
    """
    raw = http_post("/info", {"type": "l2Book", "coin": coin})
    try:
        levels = (raw or {}).get("levels") or []
        bids, asks = levels[0], levels[1]
        if is_buy and asks:
            return float(asks[0]["px"]) * 1.01
        if not is_buy and bids:
            return float(bids[0]["px"]) * 0.99
    except Exception as exc:
        logger.warning(f"[hl.venue] l2Book lookup failed for {coin}: {exc}")
    return mid_price * (1.01 if is_buy else 0.99)


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
               reduce_only: bool = False) -> Dict[str, Any]:
        """IOC (immediate-or-cancel) limit order, priced to cross the live
        book (best bid/ask + 1%) and sized up to HL's $10 floor.
        `reduce_only=True` for closes: without it, the size floor below
        could overshoot a sub-$10 position and flip it to the opposite
        side instead of flattening it."""
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}
        if mid <= 0:
            return {"ok": False, "error": f"invalid mid price for {coin}"}

        try:
            sz_dec = meta.sz_decimals(coin)
            price = _ioc_cross_price(coin, is_buy, mid)
            price_str = sizing.round_price(price, sz_dec, is_perp=True, is_buy=is_buy)
            size = max(size, sizing.min_order_size(mid, sz_dec))
            size_str = f"{size:.{sz_dec}f}"

            exchange = sdk.get_exchange()
            order_type = OrderType(limit={"tif": "Ioc"})
            result = exchange.order(
                coin, is_buy, float(size_str), float(price_str), order_type,
                reduce_only=reduce_only,
            )
            parsed = _order_result(result)
            if not parsed.get("ok"):
                logger.warning(
                    f"[hl.venue] market {coin} {'BUY' if is_buy else 'SELL'} "
                    f"size={size_str} px={price_str} rejected: {parsed.get('error')}"
                )
            return parsed
        except Exception as exc:
            logger.error(f"[hl.venue] market({coin}) failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def close(self, coin: str) -> Dict[str, Any]:
        """Reduce-only full close at market (IOC), sized off our OWN live
        position (never a caller-supplied size) so a stale size can't
        overshoot the floor and flip the position. {ok: True} with no
        error when there is nothing to close."""
        if not env.has_write_creds():
            return {"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}

        account = env.account_address()
        state = self.account_state(account)
        if state is None:
            return {"ok": False, "error": "account_state read failed"}

        pos = state["raw_positions"].get(coin)
        if pos is None:
            return {"ok": True}  # already flat
        try:
            szi = float(pos.get("szi") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_szi"}
        if szi == 0:
            return {"ok": True}  # already flat

        is_long = szi > 0
        mid_price = self.mid(coin)
        if mid_price <= 0:
            return {"ok": False, "error": f"invalid price for {coin}"}
        return self.market(coin, is_buy=not is_long, size=abs(szi), mid=mid_price, reduce_only=True)
