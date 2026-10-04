"""Fixtures for the Scout gate tests (no tests in this module). A Venue
fake with portfolio/extras/open_orders on top of discovery_fakes.FakeVenue,
and builders for HL-shaped portfolio, leaderboard and fills payloads."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from discovery_fakes import FakeVenue

DAY = 86_400_000
HOUR = 3_600_000
NOW = (int(time.time() * 1000) // DAY) * DAY - 12 * HOUR   # yesterday, UTC noon: always in the past


def addr(i: int) -> str:
    return "0x" + f"{i:040x}"


class ScoutVenue(FakeVenue):
    def __init__(self) -> None:
        super().__init__()
        self._portfolio: Dict[str, Any] = {}
        self._orders: Dict[str, Any] = {}
        self.portfolio_calls: List[str] = []
        self.orders_calls: List[str] = []
        self.block = None            # threading.Event: portfolio() waits on it (switchover test)

    def set_portfolio(self, user: str, raw: Any) -> None:
        self._portfolio[user] = raw

    def portfolio(self, user: str) -> Optional[List[Any]]:
        self.portfolio_calls.append(user)
        if self.block is not None:
            self.block.wait(5)
        return self._portfolio.get(user)

    def extras(self, user: str) -> Optional[Dict[str, Any]]:
        return {"spot_other_usd": 0.0, "staked_hype_usd": 0.0}

    def open_orders(self, user: str) -> Optional[List[Dict[str, Any]]]:
        self.orders_calls.append(user)
        return self._orders.get(user)


def lb_row(a: str, av: float, pnl30: float, pnl_all: float, vlm30: float = 1e6, name: Optional[str] = None,
           pnl1: float = 1.0, pnl7: float = 5.0) -> Dict[str, Any]:
    w = lambda p, v: {"pnl": str(p), "roi": str(p / av if av else 0), "vlm": str(v)}  # noqa: E731
    return {"ethAddress": a, "accountValue": str(av), "displayName": name, "prize": 0,
            "windowPerformances": [["day", w(pnl1, vlm30 / 30)], ["week", w(pnl7, vlm30 / 4)],
                                   ["month", w(pnl30, vlm30)], ["allTime", w(pnl_all, vlm30 * 10)]]}


def portfolio(daily_pnl: Sequence[float], av: float = 10_000.0, now: int = NOW) -> List[Any]:
    """HL portfolio raw from a list of daily PnL (oldest first, last = today).
    pnlHistory is cumulative from each window start, one point per UTC day."""
    n = len(daily_pnl)
    days = [(now // DAY) * DAY - (n - 1 - i) * DAY + HOUR for i in range(n)]

    def window(k: int) -> Dict[str, Any]:
        sel = list(range(max(0, n - k), n))
        cum, pts, avs = 0.0, [], []
        for j, i in enumerate(sel):
            if j > 0:
                cum += daily_pnl[i]
            pts.append([days[i], str(cum)])
            avs.append([days[i], str(av + cum)])
        return {"accountValueHistory": avs, "pnlHistory": pts, "vlm": "1000.0"}
    out = [["day", window(2)], ["week", window(8)], ["month", window(31)], ["allTime", window(n)]]
    return out + [["perp" + k[0].upper() + k[1:], v] for k, v in out]


def fill(t: int, coin: str, px: float, sz: float, side: str, start: float, pnl: float = 0.0,
         fee: float = 0.0) -> Dict[str, Any]:
    return {"time_ms": t, "coin": coin, "px": px, "sz": sz, "side": side, "dir": "", "start_position": start,
            "closed_pnl": pnl, "fee": fee}


def trips(coin: str, n: int, start_ms: int, every_ms: int = DAY, hold_ms: int = 6 * HOUR, px: float = 100.0,
          sz: float = 10.0, pnl: float = 5.0, fee: float = 0.5, move: float = 0.01) -> List[Dict[str, Any]]:
    """n long round trips: open at px, close at px*(1+move)."""
    out = []
    for k in range(n):
        t = start_ms + k * every_ms
        out.append(fill(t, coin, px, sz, "B", 0.0, 0.0, fee))
        out.append(fill(t + hold_ms, coin, px * (1 + move), sz, "A", sz, pnl, fee))
    return out


def flat_15m(coin_px: float, start: int, end: int) -> List[Dict[str, Any]]:
    step = 15 * 60_000
    t = (start // step) * step
    out = []
    while t <= end:
        out.append({"t": t, "o": coin_px, "h": coin_px, "l": coin_px, "c": coin_px, "v": 1.0})
        t += step
    return out
