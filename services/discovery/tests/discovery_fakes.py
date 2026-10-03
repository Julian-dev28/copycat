"""FakeVenue: an in-memory contracts.venue.Venue double for gate tests.
No network, fully controllable, records calls so incremental-cache tests
can assert on what was actually fetched."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class FakeVenue:
    def __init__(self) -> None:
        self._leaderboard: Optional[List[Dict[str, Any]]] = []
        self._fills: Dict[str, List[Dict[str, Any]]] = {}
        self._candles: Dict[tuple, List[Dict[str, Any]]] = {}
        self._account_state: Dict[str, Dict[str, Any]] = {}
        self._max_lev: Dict[str, int] = {}
        self.fills_calls: List[tuple] = []
        self.candles_calls: List[tuple] = []

    # ── fixture setters ─────────────────────────────────────────────────
    def set_leaderboard(self, rows: Optional[List[Dict[str, Any]]]) -> None:
        self._leaderboard = rows

    def set_fills(self, wallet: str, fills: List[Dict[str, Any]]) -> None:
        self._fills[wallet] = fills

    def set_candles(self, coin: str, interval: str, rows: List[Dict[str, Any]]) -> None:
        self._candles[(coin, interval)] = rows

    def set_max_leverage(self, coin: str, lev: int) -> None:
        self._max_lev[coin] = lev

    def set_account_state(self, wallet: str, state: Dict[str, Any]) -> None:
        self._account_state[wallet] = state

    # ── Venue protocol ───────────────────────────────────────────────────
    def account_state(self, user: str) -> Optional[Dict[str, Any]]:
        return self._account_state.get(user)

    def extras(self, user: str) -> Optional[Dict[str, Any]]:
        return None

    def mid(self, coin: str) -> float:
        return 0.0

    def max_leverage(self, coin: str) -> int:
        return self._max_lev.get(coin, 20)

    def is_isolated_only(self, coin: str) -> bool:
        return False

    def size_for(self, coin: str, notional_usd: float, mid: float) -> float:
        return notional_usd / mid if mid else 0.0

    def fills(self, user: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]:
        self.fills_calls.append((user, start_ms, end_ms))
        rows = self._fills.get(user, [])
        return [f for f in rows if start_ms <= f["time_ms"] <= end_ms]

    def leaderboard(self) -> Optional[List[Dict[str, Any]]]:
        return self._leaderboard

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Optional[List[Dict[str, Any]]]:
        self.candles_calls.append((coin, interval, start_ms, end_ms))
        rows = self._candles.get((coin, interval), [])
        out = [c for c in rows if start_ms <= c["t"] <= end_ms]
        return out or None

    def set_leverage(self, coin: str, leverage: int, is_cross: bool):
        raise NotImplementedError("discovery never writes")

    def market(self, coin: str, is_buy: bool, size: float, mid: float, reduce_only: bool = False):
        raise NotImplementedError("discovery never writes")

    def close(self, coin: str):
        raise NotImplementedError("discovery never writes")


def flat_candles(start_ms: int, end_ms: int, price: float, step_ms: int = 60_000) -> List[Dict[str, Any]]:
    """A flat 1m candle series: o=h=l=c=price at every minute in [start_ms, end_ms]."""
    out = []
    t = start_ms
    while t <= end_ms:
        out.append({"t": t, "o": price, "h": price, "l": price, "c": price, "v": 0.0})
        t += step_ms
    return out
