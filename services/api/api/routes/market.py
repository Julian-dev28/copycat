"""Market data reads. Sync route (threadpool): a cache miss is a live HL
read, see api.market_client."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_market_client, require_auth
from ..market_client import MarketClient, MarketUnavailable
from ..schemas import CandleQuery, CandleView

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(require_auth)])


@router.get("/candles", response_model=List[CandleView],
            responses={503: {"description": "discovery.public.candles isn't available"}})
def get_candles(
    query: CandleQuery = Query(),
    market: MarketClient = Depends(get_market_client),
) -> List[CandleView]:
    """OHLCV bars in [start_ms, end_ms], oldest first, at most 5000 bars.
    Bad interval, end <= start, or a range over the cap is 422."""
    try:
        return market.candles(query.coin, query.interval, query.start_ms, query.end_ms)
    except MarketUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
