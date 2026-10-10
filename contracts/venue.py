"""The boundary between the engine/discovery and Hyperliquid.

services/hl implements this Protocol for real (HlVenue). The engine and the
discovery sim code against it and test with fakes. Every read returns None on
failure: a failed read must never look like a flat leader or zero equity.
Every network call has a timeout (default 10s): a hung read froze pathiel's
monitor for 15 minutes once, and the SDK passes timeout=None explicitly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, TypedDict


class LeaderPosition(TypedDict):
    szi: float          # signed size
    entry_px: float     # average entry
    lev: float          # leverage value on that coin
    is_cross: bool


class AccountState(TypedDict, total=False):
    equity_perp_usd: float              # accountValue summed over main + hip3 dexes read
    spot_usdc: float
    positions: Dict[str, LeaderPosition]   # coin -> position; hip3 coins as "dex:COIN"
    available: Dict[str, float]         # dex ("" = main) -> margin free to open with. Under
                                        # unified/portfolio margin, per-dex withdrawable is not
                                        # meaningful: hl reports spot USDC total - hold for every dex.
    raw_positions: Dict[str, Dict[str, Any]]   # coin -> HL assetPosition.position (entryPx, unrealizedPnl, liquidationPx, ...)
    abstraction: str                    # HL userAbstraction: "default", "unifiedAccount",
                                        # "portfolioMargin", ... (absent when the read failed;
                                        # engine.sizing.account_equity then falls back to perp+spot)


class MarketStats(TypedDict):
    mark_px: float
    mid_px: float
    day_volume_usd: float     # dayNtlVlm
    open_interest_usd: float  # openInterest x mark
    max_leverage: int


class Extras(TypedDict):
    spot_other_usd: float     # non-USDC spot tokens at mid (illiquid marks excluded)
    staked_hype_usd: float


class Fill(TypedDict):
    time_ms: int
    coin: str
    px: float
    sz: float
    side: str           # "B" | "A"
    dir: str            # "Open Long", "Close Short", ...
    start_position: float
    closed_pnl: float
    fee: float


class OrderResult(TypedDict, total=False):
    ok: bool            # True only when the requested size FULLY filled (or rested, for GTC)
    error: str
    avg_px: float
    filled_sz: float    # always set when HL reported a fill, including partial fills
    ambiguous: bool     # the request may have reached HL (timeout, dropped connection):
                        # outcome unknown, resolve with order_status(cloid) or a fresh account read


class Venue(Protocol):
    # reads
    def account_state(self, user: str) -> Optional[AccountState]: ...
    def extras(self, user: str) -> Optional[Extras]: ...
    def mid(self, coin: str) -> float: ...                     # 0.0 on failure
    def max_leverage(self, coin: str) -> int: ...              # never silently 1
    def is_isolated_only(self, coin: str) -> bool: ...
    def size_for(self, coin: str, notional_usd: float, mid: float) -> float: ...  # rounded to szDecimals
    def fills(self, user: str, start_ms: int, end_ms: int,
              aggregate_by_time: bool = False) -> Optional[List[Fill]]: ...
        # [start_ms, end_ms] inclusive, oldest first. aggregate_by_time: one Fill per order per
        # millisecond (HL aggregateByTime): sz/closed_pnl/fee summed, px = VWAP, start_position
        # and dir from the first partial. dir can then be stale on a flip (Close Short with
        # sz past zero): classify from start_position + side + sz. Optional for implementers:
        # callers check the signature before passing it.
    def leaderboard(self) -> Optional[List[Dict[str, Any]]]: ...   # raw HL leaderboard rows
    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]: ...
    def market_stats(self, coin: str) -> Optional[MarketStats]: ...
        # from metaAndAssetCtxs (cached ~30s per dex). None on failure.
    def depth_usd(self, coin: str, is_buy: bool, max_slippage_pct: float) -> Optional[float]: ...
        # USD notional fillable on the book within max_slippage_pct of mid (l2Book). None on failure.
    def portfolio(self, user: str) -> Optional[List[Any]]: ...
        # raw HL {"type":"portfolio"}: [[window, {accountValueHistory, pnlHistory, vlm}], ...] for
        # day, week, month, allTime, perpDay, perpWeek, perpMonth, perpAllTime. None on failure.
    def open_orders(self, user: str) -> Optional[List[Dict[str, Any]]]: ...
        # raw HL {"type":"frontendOpenOrders"} rows across the dexes read. None on failure.
    def ledger_updates(self, user: str, start_ms: int) -> Optional[List[Dict[str, Any]]]: ...
        # raw HL {"type":"userNonFundingLedgerUpdates"} rows ({time, hash, delta}) with
        # time >= start_ms, oldest first, every page read. None on failure or when the
        # rows did not fit in the page budget (never a silently truncated list).
    # writes (need COPYCAT_AGENT_KEY; return ok False with error otherwise)
    def set_leverage(self, coin: str, leverage: int, is_cross: bool) -> OrderResult: ...  # strict: ok only on HL status "ok"
    def market(self, coin: str, is_buy: bool, size: float, mid: float,
               reduce_only: bool = False, cloid: Optional[str] = None,
               max_slippage_pct: float = 1.0) -> OrderResult: ...
        # IOC. Limit price capped at mid*(1 +/- max_slippage_pct/100). reduce_only orders are
        # never bumped up to the exchange minimum. cloid: 0x + 32 hex, HL client order id.
    def order_status(self, cloid: str) -> Optional[str]: ...
        # HL status for our order by cloid: "filled", "open", "canceled", "rejected", ...,
        # "unknown" when HL has no such order, None when the read itself failed.
    def close(self, coin: str, cloid: Optional[str] = None) -> OrderResult: ...
        # reduce-only full close sized from a fresh read; ok only if the position is now flat
