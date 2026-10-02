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


class AccountState(TypedDict):
    equity_perp_usd: float              # accountValue summed over main + hip3 dexes read
    spot_usdc: float
    positions: Dict[str, LeaderPosition]   # coin -> position; hip3 coins as "dex:COIN"
    available: Dict[str, float]         # dex ("" = main) -> withdrawable margin
    raw_positions: Dict[str, Dict[str, Any]]   # coin -> HL assetPosition.position (entryPx, unrealizedPnl, liquidationPx, ...)


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
    ok: bool
    error: str
    avg_px: float
    filled_sz: float


class Venue(Protocol):
    # reads
    def account_state(self, user: str) -> Optional[AccountState]: ...
    def extras(self, user: str) -> Optional[Extras]: ...
    def mid(self, coin: str) -> float: ...                     # 0.0 on failure
    def max_leverage(self, coin: str) -> int: ...              # never silently 1
    def is_isolated_only(self, coin: str) -> bool: ...
    def size_for(self, coin: str, notional_usd: float, mid: float) -> float: ...  # rounded to szDecimals
    def fills(self, user: str, start_ms: int, end_ms: int) -> Optional[List[Fill]]: ...
    def leaderboard(self) -> Optional[List[Dict[str, Any]]]: ...   # raw HL leaderboard rows
    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]: ...
    # writes (need COPYCAT_AGENT_KEY; return ok False with error otherwise)
    def set_leverage(self, coin: str, leverage: int, is_cross: bool) -> OrderResult: ...  # strict: ok only on HL status "ok"
    def market(self, coin: str, is_buy: bool, size: float, mid: float,
               reduce_only: bool = False) -> OrderResult: ...  # IOC with slippage
    def close(self, coin: str) -> OrderResult: ...             # reduce-only full close
