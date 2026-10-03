"""Adapter for GET /api/market/candles: a thin read through discovery's
candles cache (data/discovery.db, filled from HL candleSnapshot on a miss).
Calls `discovery.public.candles(coin, interval, start_ms, end_ms)`, imported
lazily: 503 while discovery doesn't expose it. The api never reaches into
discovery.candles_cache directly (contracts-at-the-boundary rule).

A cache miss is a live HL read (weight 20 + 1 per 60 bars) in this process,
on the threadpool (sync route), so the first call flips the process to
COPYCAT_HL_PRIORITY=background, same as api.scout_client.
"""
from __future__ import annotations

import os
from typing import Any, List, Protocol

from .schemas import CandleView


class MarketUnavailable(RuntimeError):
    """discovery.public.candles isn't importable. Routes map this to 503."""


class MarketClient(Protocol):
    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[CandleView]: ...


class RealMarketClient:
    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[CandleView]:
        try:
            from discovery import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise MarketUnavailable(f"services/discovery isn't importable: {e}") from e
        fn = getattr(public, "candles", None)
        if fn is None:
            raise MarketUnavailable("discovery.public has no candles() yet")
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        return [CandleView.model_validate(_plain(c)) for c in fn(coin, interval, start_ms, end_ms)]


def _plain(v: Any) -> Any:
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v
