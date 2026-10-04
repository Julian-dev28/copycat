"""Hand-built fills, 1h bars and a fake venue for the thesis gate tests.
No network. Imported by the other test_thesis_* modules (holds no tests)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence, Tuple

from discovery.thesis.indicators import Bars
from discovery_fakes import FakeVenue

H = 3_600_000
D = 86_400_000
# Monday 2026-09-07 00:00 UTC
T0 = int(dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc).timestamp() * 1000)
ADDR = "0x" + "ab" * 20


def bars_from_closes(closes: Sequence[float], start_ms: int = T0, spread: float = 0.001) -> Bars:
    rows = [{"t_ms": start_ms + i * H, "o": c, "h": c * (1 + spread), "l": c * (1 - spread), "c": c}
            for i, c in enumerate(closes)]
    return Bars.from_rows(rows)


def candle_rows(closes: Sequence[float], start_ms: int = T0, spread: float = 0.001) -> List[Dict[str, Any]]:
    """HL-shaped raw candles (t, o, h, l, c, v) for FakeVenue.set_candles."""
    return [{"t": start_ms + i * H, "o": c, "h": c * (1 + spread), "l": c * (1 - spread), "c": c, "v": 1.0}
            for i, c in enumerate(closes)]


def fill(t: int, coin: str, side: str, sz: float, px: float, start: float, closed_pnl: float = 0.0,
         fee: float = 0.0) -> Dict[str, Any]:
    return {"time_ms": t, "coin": coin, "px": px, "sz": sz, "side": side, "dir": "",
            "start_position": start, "closed_pnl": closed_pnl, "fee": fee}


def trip_fills(coin: str, side: str, t_open: int, px_in: float, t_close: int, px_out: float,
               sz: float = 1.0, adds: Sequence[Tuple[int, float, float]] = (),
               partial_exits: Sequence[Tuple[int, float, float]] = (), fee: float = 0.0) -> List[Dict[str, Any]]:
    """One flat-to-flat trip. adds/partial_exits: (t, sz, px). closed_pnl is
    (exit px - avg entry) * sz signed by side, so net PnL is exact."""
    sign = 1.0 if side == "long" else -1.0
    buy, sell = ("B", "A") if side == "long" else ("A", "B")
    out = [fill(t_open, coin, buy, sz, px_in, 0.0, fee=fee)]
    pos, cost = sz, sz * px_in
    for t, s, px in adds:
        out.append(fill(t, coin, buy, s, px, sign * pos, fee=fee))
        pos += s
        cost += s * px
    for t, s, px in partial_exits:
        avg = cost / pos
        out.append(fill(t, coin, sell, s, px, sign * pos, closed_pnl=sign * (px - avg) * s, fee=fee))
        cost -= avg * s
        pos -= s
    avg = cost / pos
    out.append(fill(t_close, coin, sell, pos, px_out, sign * pos, closed_pnl=sign * (px_out - avg) * pos, fee=fee))
    return out


def portfolio(points: Sequence[Tuple[int, float]]) -> List[Any]:
    body = {"accountValueHistory": [[t, str(v)] for t, v in points], "pnlHistory": [], "vlm": "0"}
    return [["month", body], ["allTime", body]]


class ThesisVenue(FakeVenue):
    """FakeVenue plus `portfolio` and call counters."""

    def __init__(self) -> None:
        super().__init__()
        self._portfolio: Dict[str, Optional[List[Any]]] = {}
        self.portfolio_calls = 0

    def set_portfolio(self, wallet: str, raw: Optional[List[Any]]) -> None:
        self._portfolio[wallet] = raw

    def portfolio(self, user: str) -> Optional[List[Any]]:
        self.portfolio_calls += 1
        return self._portfolio.get(user)

    def open_orders(self, user: str):
        return []
