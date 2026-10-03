"""Shared test fixtures: a FakeVenue implementing contracts.venue.Venue, and
a couple of well-known addresses used across the suite."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set



OUR = "0x" + "0" * 40
LEADER1 = "0x95da8596c44dd09f4b8becce87ad3b7894fb2328"
LEADER2 = "0xac142fee46f8dacbfef23e1e41d79f1f7233487e"
LEADER3 = "0xe2823659be02e0f48a4660e4da008b5e1abfdf29"


class FakeVenue:
    """Implements `contracts.venue.Venue` end to end. `hold()` sets up one
    user's full `account_state` in one call -- it works identically for a
    leader or for OUR own address, since the real Venue protocol uses the
    exact same `AccountState` shape for both."""

    def __init__(self) -> None:
        self.accounts: Dict[str, Optional[Dict[str, Any]]] = {}
        self.extras_map: Dict[str, Optional[Dict[str, Any]]] = {}
        self.mids: Dict[str, float] = {}
        self.max_levs: Dict[str, int] = {}
        self.isolated_only: Set[str] = set()
        self.orders: List[tuple] = []
        self.closes: List[str] = []
        self.levs: Dict[str, Dict[str, Any]] = {}
        self.fail_market: Set[str] = set()
        self.fail_close: bool = False
        # contract v2 behaviors
        # partial fills: coin -> fraction of the requested size that fills (ok False when < 1)
        self.fill_frac: Dict[str, float] = {}
        # close(): coin -> filled_sz of a partial close (ok False: not flat)
        self.close_filled: Dict[str, float] = {}
        self.ambiguous: Set[str] = set()          # market() on these coins: outcome unknown
        self.close_ambiguous: Set[str] = set()
        self.statuses: Dict[str, Optional[str]] = {}   # cloid -> order_status answer
        self.cloids: List[Optional[str]] = []
        self.raise_on_mid: Set[str] = set()

    # ── setup helpers (not part of the Venue protocol) ──────────────────

    def hold(self, user: str, coin: str, szi: float, entry_px: float = 100.0, lev: float = 3.0,
              is_cross: bool = False, equity_perp_usd: float = 1_000_000.0, spot_usdc: float = 0.0,
              available: Optional[Dict[str, float]] = None, unrealized_pnl: float = 0.0,
              liquidation_px: Optional[float] = None) -> None:
        acct = self.accounts.get(user)
        if not isinstance(acct, dict):
            acct = {"equity_perp_usd": equity_perp_usd, "spot_usdc": spot_usdc,
                    "positions": {}, "available": available or {"": equity_perp_usd, "xyz": 0.0},
                    "raw_positions": {}}
            self.accounts[user] = acct
        acct["equity_perp_usd"] = equity_perp_usd
        acct["spot_usdc"] = spot_usdc
        if available is not None:
            acct["available"] = available
        if szi:
            acct["positions"][coin] = {"szi": szi, "entry_px": entry_px, "lev": lev,
                                        "is_cross": is_cross}
            acct["raw_positions"][coin] = {
                "entryPx": entry_px, "unrealizedPnl": unrealized_pnl,
                "liquidationPx": liquidation_px, "positionValue": abs(szi) * entry_px,
            }
        else:
            acct["positions"].pop(coin, None)
            acct["raw_positions"].pop(coin, None)

    def set_account(self, user: str, equity_perp_usd: float = 1000.0, spot_usdc: float = 0.0,
                     available: Optional[Dict[str, float]] = None) -> None:
        """Set a user's equity/available WITHOUT touching any position --
        for setting up OUR OWN account when it holds no copies yet."""
        acct = self.accounts.get(user)
        if not isinstance(acct, dict):
            acct = {"positions": {}, "raw_positions": {}}
            self.accounts[user] = acct
        acct["equity_perp_usd"] = equity_perp_usd
        acct["spot_usdc"] = spot_usdc
        acct["available"] = available if available is not None else {"": equity_perp_usd, "xyz": 0.0}

    def fail_account(self, user: str) -> None:
        self.accounts[user] = None

    def set_available(self, user: str, available: Dict[str, float]) -> None:
        acct = self.accounts.get(user)
        if not isinstance(acct, dict):
            acct = {"equity_perp_usd": 0.0, "spot_usdc": 0.0, "positions": {},
                    "available": {}, "raw_positions": {}}
            self.accounts[user] = acct
        acct["available"] = available

    # ── contracts.venue.Venue ───────────────────────────────────────────

    def account_state(self, user: str) -> Optional[Dict[str, Any]]:
        return self.accounts.get(user)

    def extras(self, user: str) -> Optional[Dict[str, Any]]:
        return self.extras_map.get(user)

    def mid(self, coin: str) -> float:
        if coin in self.raise_on_mid:
            raise RuntimeError(f"mid blew up for {coin}")
        return self.mids.get(coin, 100.0)

    def max_leverage(self, coin: str) -> int:
        return self.max_levs.get(coin, 50)

    def is_isolated_only(self, coin: str) -> bool:
        return coin in self.isolated_only

    def size_for(self, coin: str, notional_usd: float, mid: float) -> float:
        return notional_usd / mid if mid else 0.0

    def fills(self, user: str, start_ms: int, end_ms: int):
        return None

    def leaderboard(self):
        return None

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int):
        return None

    def set_leverage(self, coin: str, leverage: int, is_cross: bool) -> Dict[str, Any]:
        self.levs[coin] = {"leverage": leverage, "is_cross": is_cross}
        return {"ok": True}

    def market(self, coin: str, is_buy: bool, size: float, mid: float,
               reduce_only: bool = False, cloid: Optional[str] = None,
               max_slippage_pct: float = 1.0) -> Dict[str, Any]:
        self.cloids.append(cloid)
        if coin in self.fail_market:
            return {"ok": False, "error": "rejected"}
        self.orders.append((coin, is_buy, round(size, 6), reduce_only))
        if coin in self.ambiguous:
            return {"ok": False, "ambiguous": True, "error": "timeout"}
        if coin in self.fill_frac:
            frac = self.fill_frac[coin]
            return {"ok": frac >= 1.0, "filled_sz": size * frac, "avg_px": mid}
        return {"ok": True, "filled_sz": size, "avg_px": mid}

    def order_status(self, cloid: str) -> Optional[str]:
        return self.statuses.get(cloid, "unknown")

    def close(self, coin: str, cloid: Optional[str] = None) -> Dict[str, Any]:
        if self.fail_close:
            return {"ok": False, "error": "failed"}
        self.closes.append(coin)
        if coin in self.close_ambiguous:
            return {"ok": False, "ambiguous": True, "error": "timeout"}
        if coin in self.close_filled:
            return {"ok": False, "filled_sz": self.close_filled[coin], "error": "not flat"}
        return {"ok": True}


