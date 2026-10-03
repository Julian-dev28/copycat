"""Pure HL order-sizing math: price rounding to HL's tick + significant-
figure rules, and size rounding to the coin's szDecimals with the $10
minimum-order floor enforced. No network calls except the one `meta`
lookup each function needs for the coin's precision.
"""
from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, getcontext
from typing import Optional

from . import meta

# Hyperliquid rejects any order below $10 notional. Target a small buffer
# above it so IOC price offset + mark-vs-limit rounding can't dip under.
MIN_ORDER_USD = 10.5


def round_price(price: float, sz_decimals: int, is_perp: bool = True,
                is_buy: Optional[bool] = None) -> str:
    """Round a price to satisfy Hyperliquid's two constraints:

    1. At most MAX_DECIMALS - sz_decimals decimal places, where
       MAX_DECIMALS = 6 for perps, 8 for spot.
    2. At most 5 significant figures, counted from the first non-zero
       digit (so 0.000123456 has decimals for 5 sig figs = 9, not 5).
       Integer prices are always allowed, whatever their digit count.

    The old version counted sig figs as `5 - integer digits` with integer
    digits floored at 0, which treats every sub-$1 price as if it started
    at the tenths place: 0.000123 got 5 decimals and a buy rounded up to
    0.00013, a 5.7% worse limit than asked for.

    `is_buy` controls rounding direction so an IOC limit always rounds in
    the direction of MORE aggression (preserves cross-the-book intent):
      * BUY -> ROUND_CEILING (round UP; limit stays at/above ask)
      * SELL -> ROUND_FLOOR (round DOWN; limit stays at/below bid)
    Without this, a SELL price 1% below the bid can half-up-round to a
    price ABOVE the bid, and the IOC can never match ("could not
    immediately match"). `None` falls back to ROUND_HALF_UP for
    non-order call sites (e.g. trigger prices).
    """
    getcontext().prec = 28
    if price <= 0:
        return "0"

    max_decimals = 6 if is_perp else 8
    px_decimals_by_tick = max(0, max_decimals - int(sz_decimals))

    # Decimal.adjusted() = exponent of the most significant digit, exact
    # (no float log10 edge at powers of ten): 85002.3 -> 4, 0.5 -> -1,
    # 0.000123 -> -4. Decimals allowed for 5 sig figs = 4 - adjusted.
    msd_exp = Decimal(str(price)).adjusted()
    px_decimals_by_sigfig = max(0, 4 - msd_exp)
    px_decimals = min(px_decimals_by_tick, px_decimals_by_sigfig)

    if is_buy is True:
        rounding_mode = ROUND_CEILING
    elif is_buy is False:
        rounding_mode = ROUND_FLOOR
    else:
        rounding_mode = ROUND_HALF_UP

    q = Decimal(10) ** -px_decimals if px_decimals > 0 else Decimal(1)
    rounded = (Decimal(str(price)) / q).quantize(Decimal(1), rounding=rounding_mode) * q
    if px_decimals > 0:
        return f"{rounded:.{px_decimals}f}"
    return f"{rounded:.0f}"


def min_order_size(price: float, sz_decimals: int) -> float:
    """Smallest size at the coin's precision worth at least MIN_ORDER_USD.

    Rounded UP to the size tick (10^-sz_decimals): for integer-size coins
    (sz_decimals=0) a plain round-to-precision would drop a near-$10 size
    under HL's floor.
    """
    if price <= 0:
        return 0.0
    tick = 10.0 ** (-sz_decimals)
    return math.ceil((MIN_ORDER_USD / price) / tick) * tick


def order_size(size: float, mid_price: float, sz_dec: int, reduce_only: bool) -> float:
    """The size `market()` actually sends: rounded to szDecimals, and for an
    OPEN bumped up to the $10.50 floor. A reduce_only order is NEVER bumped:
    a bump on a sub-$10 reduce would be an order for more than the position
    (best case HL rejects it, worst case a later non-reduce retry flips the
    position). It is sent at its own size and HL decides."""
    if not reduce_only:
        size = max(size, min_order_size(mid_price, sz_dec))
    return float(f"{size:.{sz_dec}f}")


def size_for_notional(coin: str, notional_usd: float, mid_price: float,
                      reduce_only: bool = False) -> float:
    """Coin size for an intended dollar notional, rounded to the coin's
    szDecimals and (opens only) bumped up to HL's $10 floor if the raw size
    would fall under it. Mirrors exactly what `market()`'s own sizing does,
    so a caller's risk gates and bookkeeping match the order that will
    actually be sent. 0.0 for an invalid input."""
    if notional_usd <= 0 or mid_price <= 0:
        return 0.0
    sz_dec = meta.sz_decimals(coin)
    return order_size(notional_usd / mid_price, mid_price, sz_dec, reduce_only)
