"""Strategy-thesis routes, under the Scout trader file. Sync `def` routes
(threadpool). The slow fingerprint compute is queued on
app.state.fingerprint_jobs and runs in a child process; these routes only
read its cache, so they never block on it (202 + ScoutStatus while it
builds, same contract as the profile route).
"""
from __future__ import annotations

import time
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from contracts.models import ScoutStatus, StrategyFingerprint, Thesis, TradeExample

from ..deps import get_thesis_client, require_auth
from ..fingerprint_jobs import FingerprintJobs, QueueFull
from ..schemas import TRADES_MAX_LIMIT, ThesisWrite
from ..thesis_client import FingerprintFailed, ThesisClient, ThesisUnavailable
from .scout import valid_address

router = APIRouter(prefix="/api/scout", tags=["thesis"], dependencies=[Depends(require_auth)])

_SOURCES = ("ta", "claude_code")          # response order of GET .../thesis
_BUILDING = {202: {"model": ScoutStatus, "description": "fingerprint is being computed; poll again"},
             404: {"description": "not a 0x address"},
             429: {"description": "fingerprint queue full; retry later"},
             502: {"description": "the fingerprint compute failed (next GET retries)"},
             503: {"description": "discovery.thesis isn't importable"}}


def _jobs(request: Request) -> FingerprintJobs:
    return request.app.state.fingerprint_jobs


def _fingerprint_or_status(request: Request, client: ThesisClient, address: str, window_days: int) -> Any:
    try:
        out = _jobs(request).get(client, address, window_days)
    except ThesisUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except FingerprintFailed as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"fingerprint failed: {e}") from e
    except QueueFull as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from e
    except Exception as e:  # noqa: BLE001 -- a fake/real client bug, surfaced once, then retried
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"fingerprint failed: {type(e).__name__}: {e}") from e
    if isinstance(out, ScoutStatus):
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=out.model_dump(mode="json"))
    return out


@router.get("/traders/{address}/fingerprint", response_model=StrategyFingerprint, responses=_BUILDING)
def get_fingerprint(
    request: Request,
    address: str = Depends(valid_address),
    window_days: int = Query(30, ge=7, le=90),
    thesis: ThesisClient = Depends(get_thesis_client),
) -> Any:
    """Deterministic strategy fingerprint from fills + candles. Cached 15 min
    per (address, window_days); a stale one is served while a refresh runs."""
    return _fingerprint_or_status(request, thesis, address, window_days)


@router.get("/traders/{address}/trades", response_model=List[TradeExample], responses=_BUILDING)
def get_trades(
    request: Request,
    address: str = Depends(valid_address),
    limit: int = Query(TRADES_MAX_LIMIT, ge=1, le=TRADES_MAX_LIMIT),
    thesis: ThesisClient = Depends(get_thesis_client),
) -> Any:
    """Representative round trips WITH entry context (`TradeExample`), the
    evidence behind the 30d fingerprint's claims (largest win, typical
    breakout entry, ...). TradeExample, not RoundTrip, because the entry
    context is the point for a thesis; the full RoundTrip list (no context)
    is `TraderProfile.recent_trips`. Same 202 while the fingerprint builds."""
    out = _fingerprint_or_status(request, thesis, address, 30)
    if isinstance(out, JSONResponse):
        return out
    return out.examples[:limit]


@router.get("/traders/{address}/thesis", response_model=List[Thesis],
            responses={404: {"description": "not a 0x address"},
                       503: {"description": "discovery.thesis isn't importable"}})
def get_thesis(
    address: str = Depends(valid_address),
    thesis: ThesisClient = Depends(get_thesis_client),
) -> List[Thesis]:
    """Latest thesis per source, "ta" first then "claude_code". Empty list
    when none exist. Never computes: the "ta" one is refreshed by each
    fingerprint compute."""
    try:
        all_ = thesis.theses(address)
    except ThesisUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    latest = {}
    for t in all_:
        if t.source not in latest or t.created_ms > latest[t.source].created_ms:
            latest[t.source] = t
    return [latest[s] for s in _SOURCES if s in latest]


@router.put("/traders/{address}/thesis", response_model=Thesis,
            responses={404: {"description": "not a 0x address"},
                       503: {"description": "discovery.thesis isn't importable"}})
def put_thesis(
    request: Request,
    body: ThesisWrite,
    address: str = Depends(valid_address),
    thesis: ThesisClient = Depends(get_thesis_client),
) -> Thesis:
    """Saves a "claude_code" thesis (the copycat MCP server's write path).
    `source`, `address`, `created_ms` are server-set; `fingerprint_as_of_ms`
    links it to the cached 30d fingerprint when there is one."""
    fp = _jobs(request).peek(address, 30)
    t = Thesis(address=address, source="claude_code", created_ms=int(time.time() * 1000),
               title=body.title.strip(), markdown=body.markdown, author=body.author,
               fingerprint_as_of_ms=fp.as_of_ms if fp else None)
    try:
        thesis.save(t)
    except ThesisUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return t
