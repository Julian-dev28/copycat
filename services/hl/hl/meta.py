"""Cached Hyperliquid metadata: per-dex perp universes, the HIP-3 dex list,
and spot USDC pricing. All three change rarely, but the engine calls them
every cycle for up to 10 leaders -- TTL caches keep that from re-hitting
/info on every single lookup.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .http import http_post

logger = logging.getLogger(__name__)

META_TTL_S = float(os.environ.get("COPYCAT_HL_META_TTL_S", "3600"))
DEX_LIST_TTL_S = float(os.environ.get("COPYCAT_HL_DEX_LIST_TTL_S", "86400"))
SPOT_PRICE_TTL_S = float(os.environ.get("COPYCAT_HL_SPOT_PRICE_TTL_S", "30"))

_universe_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_dex_list_cache: Tuple[float, List[str]] = (0.0, [])
_spot_price_cache: Tuple[float, Optional[Dict[str, Tuple[float, float]]]] = (0.0, None)


def reset_caches() -> None:
    """Test hook: clear every cache so a monkeypatched http_post is
    actually exercised instead of serving a previous call's cached entry."""
    global _dex_list_cache, _spot_price_cache
    _universe_cache.clear()
    _dex_list_cache = (0.0, [])
    _spot_price_cache = (0.0, None)


def universe(dex: str = "", force_refresh: bool = False) -> List[Dict[str, Any]]:
    """The `universe` list for one dex ("" = main perp dex), cached for
    META_TTL_S. On a fetch failure, serves a stale cached copy if one
    exists rather than an empty list -- a transient API blip must not
    blank coin resolution mid-cycle."""
    key = dex or ""
    hit = _universe_cache.get(key)
    now = time.time()
    if hit and not force_refresh and (now - hit[0]) < META_TTL_S:
        return hit[1]
    payload: Dict[str, Any] = {"type": "meta"}
    if dex:
        payload["dex"] = dex
    raw = http_post("/info", payload)
    u = (raw or {}).get("universe") if isinstance(raw, dict) else None
    if u:
        _universe_cache[key] = (now, u)
        return u
    if hit:
        logger.warning(f"[hl.meta] meta fetch failed for dex={dex!r}; serving stale cache")
        return hit[1]
    logger.warning(f"[hl.meta] meta fetch failed for dex={dex!r}; no cache to fall back on")
    return []


def perp_dexs(force_refresh: bool = False) -> List[str]:
    """Every registered HIP-3 perp dex name (the main dex's `null` entry is
    excluded), cached for DEX_LIST_TTL_S. On a fetch failure/empty
    response, serves the last known list -- dex registration changes are
    rare; an empty read is far more likely a transient blip than reality."""
    global _dex_list_cache
    ts, cached = _dex_list_cache
    now = time.time()
    if cached and not force_refresh and (now - ts) < DEX_LIST_TTL_S:
        return cached
    raw = http_post("/info", {"type": "perpDexs"})
    names = [d["name"] for d in raw if isinstance(d, dict) and d.get("name")] if isinstance(raw, list) else []
    if names:
        _dex_list_cache = (now, names)
        return names
    if cached:
        logger.warning("[hl.meta] perpDexs fetch failed/empty; serving stale dex list")
        return cached
    return []


def dex_list(override: Optional[List[str]] = None) -> List[str]:
    """The dex read set for account/leader state: main dex ("") plus every
    registered HIP-3 dex, by default.

    Configurable two ways: pass `override` directly, or set
    COPYCAT_HL_DEXES to a comma-separated list ("", "xyz" for main+xyz
    only) -- the env var is for ops/local tuning, `override` is for callers
    that already resolved a dex list. `override` wins when both are given.
    """
    if override is not None:
        return list(override)
    env_override = os.environ.get("COPYCAT_HL_DEXES")
    if env_override is not None:
        return [d.strip() for d in env_override.split(",")]
    return [""] + perp_dexs()


def sz_decimals(coin: str) -> int:
    """Size precision for `coin`. Defaults to 5 (HL's most common) when the
    coin can't be resolved -- still safer to round an order with a guessed
    precision than to refuse sizing outright; the $10-floor check downstream
    still applies regardless."""
    for u in universe():
        if u.get("name") == coin:
            return int(u.get("szDecimals", 5))
    if ":" in coin:
        dex = coin.split(":", 1)[0]
        for u in universe(dex=dex):
            if u.get("name") == coin:
                return int(u.get("szDecimals", 5))
    logger.warning(f"[hl.meta] unknown coin {coin!r}; defaulting szDecimals=5")
    return 5


def is_isolated_only(coin: str) -> bool:
    """True if the market only supports isolated margin (no cross). Most
    HIP-3 markets are isolated-only; calling update_leverage(is_cross=True)
    on one silently fails on the exchange, after which the next order is
    rejected ("Insufficient margin to place order") even with plenty of
    free equity -- no isolated-margin position was actually opened first.
    Defaults to False (cross) on a lookup failure, so native-coin behavior
    is preserved rather than forcing isolated margin on everything during
    an outage."""
    try:
        for u in universe():
            if u.get("name") == coin:
                return bool(u.get("onlyIsolated", False))
        if ":" in coin:
            dex = coin.split(":", 1)[0]
            for u in universe(dex=dex):
                if u.get("name") == coin:
                    return bool(u.get("onlyIsolated", False))
    except Exception as exc:
        logger.warning(f"[hl.meta] is_isolated_only lookup failed for {coin}: {exc}")
    return False


def max_leverage(coin: str) -> int:
    """The coin's maximum allowed exchange leverage. 0 means "could not
    determine" -- the same None/0.0 failure convention every other read in
    this package uses -- and this must NEVER silently fall back to 1.

    Why: callers do `min(requested, max_leverage(coin))`. A silent 1 here
    opens a position at 1x when the book asked for e.g. 20x -- it doesn't
    error, it just quietly mis-sizes every position by 20x smaller margin
    usage than the risk model assumed. pathiel hit exactly this on
    2026-09-08: a cold, partially-warmed meta cache was missing
    `maxLeverage` for a coin, the old code fell back to 1, and two
    positions opened at 1x while the config said 3x -- discovered only by
    reading the fill log after the fact. The fix: if a cached entry for the
    coin is found but has no usable `maxLeverage`, force ONE refresh before
    giving up, instead of trusting a cache that is warm-but-incomplete.
    """
    def _lev(entry: Dict[str, Any]) -> Optional[int]:
        try:
            v = int(entry.get("maxLeverage") or 0)
        except (TypeError, ValueError):
            return None
        return v if v >= 1 else None

    for u in universe():
        if u.get("name") == coin:
            v = _lev(u)
            if v:
                return v
    if ":" in coin:
        dex = coin.split(":", 1)[0]
        for refresh in (False, True):
            try:
                for u in universe(dex=dex, force_refresh=refresh):
                    if u.get("name") == coin:
                        v = _lev(u)
                        if v:
                            return v
            except Exception as exc:
                logger.warning(f"[hl.meta] max_leverage lookup failed for dex={dex} (refresh={refresh}): {exc}")
    logger.error(f"[hl.meta] no usable maxLeverage for {coin!r} -- returning 0 (never silently 1)")
    return 0


def spot_prices(force_refresh: bool = False) -> Optional[Dict[str, Tuple[float, float]]]:
    """{token name: (USDC mid price, 24h pair notional volume)} for every
    spot token with a USDC pair, built from one `spotMetaAndAssetCtxs` call
    and cached for SPOT_PRICE_TTL_S (the engine calls `extras()` for up to
    10 leaders every cycle and would otherwise re-fetch the same ~300KB
    payload 10x per cycle).

    Each token's price/volume is read via its universe entry's own
    `index` field into `ctxs` -- NOT the entry's position in the
    `universe` list. The two are not guaranteed to line up (and HL's own
    `universe` entries are not sorted by `index`), so indexing by list
    position silently prices the wrong pair.

    Falls back to `markPx` when `midPx` is missing. Returns None on a
    fetch/parse failure -- never a stale map served past its TTL, and
    never an empty-but-successful-looking {}. A token with no USDC pair is
    simply absent from the map; callers treat "absent" as "can't price
    this one," not as a failed read.
    """
    global _spot_price_cache
    ts, cached = _spot_price_cache
    now = time.time()
    if cached is not None and not force_refresh and (now - ts) < SPOT_PRICE_TTL_S:
        return cached

    raw = http_post("/info", {"type": "spotMetaAndAssetCtxs"})
    if not (isinstance(raw, list) and len(raw) == 2):
        return None
    meta_obj, ctxs = raw[0], raw[1]
    tokens = (meta_obj or {}).get("tokens") if isinstance(meta_obj, dict) else None
    uni = (meta_obj or {}).get("universe") if isinstance(meta_obj, dict) else None
    if not isinstance(tokens, list) or not isinstance(uni, list) or not isinstance(ctxs, list):
        return None

    idx_to_name = {t.get("index"): t.get("name") for t in tokens if isinstance(t, dict)}
    usdc_idx = next((i for i, n in idx_to_name.items() if n == "USDC"), 0)

    prices: Dict[str, Tuple[float, float]] = {}
    for u in uni:
        pair = u.get("tokens") if isinstance(u, dict) else None
        if not isinstance(pair, list) or len(pair) != 2 or usdc_idx not in pair:
            continue
        base_idx = pair[0] if pair[1] == usdc_idx else pair[1]
        name = idx_to_name.get(base_idx)
        if not name:
            continue
        ctx_idx = u.get("index")  # into `ctxs` -- NOT u's position in `uni`
        if not isinstance(ctx_idx, int) or ctx_idx < 0 or ctx_idx >= len(ctxs):
            continue
        ctx = ctxs[ctx_idx] or {}
        px = ctx.get("midPx")
        if px in (None, ""):
            px = ctx.get("markPx")
        try:
            pxf = float(px)
            vlm = float(ctx.get("dayNtlVlm") or 0)
        except (TypeError, ValueError):
            continue
        if pxf > 0 and name not in prices:
            prices[name] = (pxf, vlm)

    _spot_price_cache = (now, prices)
    return prices
