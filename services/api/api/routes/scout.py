"""Scout routes (docs/research/copytrading_page_spec.md section 8). Every
route is a sync `def`, so FastAPI runs it on its threadpool and the event
loop stays free for the kill-switch routes; see api/scout_client.py for why
reads and what-if stay in this process while the board build does not.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from contracts.models import (
    CustomWallet,
    CustomWalletRequest,
    LeaderFillView,
    OpenOrderView,
    ScoutPresets,
    ScoutSimTerms,
    ScoutStatus,
    TraderPage,
    TraderProfile,
    WhatIfRequest,
    WhatIfResult,
    norm_addr,
)

from ..deps import get_scout_client, get_store, require_auth
from ..schemas import SCOUT_FILLS_MAX_LIMIT, ScoutQuery
from ..scout_client import ScoutBusy, ScoutClient, ScoutUnavailable
from ..settings_store import SettingsStore

router = APIRouter(prefix="/api/scout", tags=["scout"], dependencies=[Depends(require_auth)])

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_NOT_FOUND = {404: {"description": "not a 0x address, or no data for it"}}
_UNAVAILABLE = {503: {"description": "discovery.scout isn't importable"}}


def valid_address(address: str) -> str:
    """Path param -> normalized address. 404 (not 422) for anything that
    isn't a 0x address: there is no such trader file (spec section 8)."""
    a = address.strip()
    if not _ADDR_RE.match(a):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"not a 0x address: {address!r}")
    return norm_addr(a)


def _unavailable(e: ScoutUnavailable) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))


def _etag(page: TraderPage, book: set) -> str:
    """Spec 7.3 keys the list on refresh_id:settings_hash. `in_book` is
    filled here from Settings.leaders, so the book is part of the tag too:
    adding a leader must not let the web keep a cached 304 with the old
    in_book flags."""
    book_h = hashlib.sha1(",".join(sorted(book)).encode()).hexdigest()[:10]
    return f'W/"{page.refresh_id}:{page.settings_hash}:{book_h}"'


@router.get("/traders", response_model=TraderPage, responses={304: {"description": "ETag matched"},
                                                              **_UNAVAILABLE})
def list_traders(
    request: Request,
    response: Response,
    query: ScoutQuery = Query(),
    store: SettingsStore = Depends(get_store),
    scout: ScoutClient = Depends(get_scout_client),
) -> Any:
    try:
        page = scout.page(query.to_discovery())
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
    book = set(store.load().leaders)
    for row in page.rows:
        row.in_book = norm_addr(row.address) in book
    tag = _etag(page, book)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    return page


@router.get(
    "/traders/{address}",
    response_model=TraderProfile,
    responses={202: {"model": ScoutStatus, "description": "profile is being built; poll again"},
               **_NOT_FOUND, **_UNAVAILABLE},
)
def get_trader(
    address: str = Depends(valid_address),
    store: SettingsStore = Depends(get_store),
    scout: ScoutClient = Depends(get_scout_client),
) -> Any:
    try:
        out = scout.profile(address)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no Scout data for {address}")
    if isinstance(out, ScoutStatus):
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=out.model_dump(mode="json"))
    out.row.in_book = norm_addr(out.row.address) in set(store.load().leaders)
    return out


@router.get("/traders/{address}/fills", response_model=List[LeaderFillView],
            responses={**_NOT_FOUND, **_UNAVAILABLE})
def get_trader_fills(
    address: str = Depends(valid_address),
    before_ms: Optional[int] = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=SCOUT_FILLS_MAX_LIMIT),
    scout: ScoutClient = Depends(get_scout_client),
) -> List[LeaderFillView]:
    try:
        return scout.fills(address, before_ms, limit)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


@router.get("/traders/{address}/orders", response_model=List[OpenOrderView],
            responses={**_NOT_FOUND, **_UNAVAILABLE})
def get_trader_orders(
    address: str = Depends(valid_address),
    scout: ScoutClient = Depends(get_scout_client),
) -> List[OpenOrderView]:
    """Live open orders (HL weight 20, cached 30 s by discovery)."""
    try:
        return scout.orders(address)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


@router.post("/traders/{address}/what-if", response_model=WhatIfResult,
             responses={409: {"description": "a what-if is already running"},
                        **_NOT_FOUND, **_UNAVAILABLE})
def what_if(
    request: Request,
    body: WhatIfRequest,
    address: str = Depends(valid_address),
    store: SettingsStore = Depends(get_store),
    scout: ScoutClient = Depends(get_scout_client),
) -> WhatIfResult:
    """Sim of this one wallet at the CURRENT settings file merged with
    `body.override`, on cached fills and candles only. One at a time per api
    process: a second request while one runs is 409, never queued (a queue
    of sims would just pile up threadpool workers)."""
    lock = request.app.state.scout_what_if_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "a what-if is already running")
    try:
        return scout.what_if(address, store.load(), body.sim_equity_usd, body.override)
    except ScoutBusy as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
    finally:
        lock.release()


@router.get("/presets", response_model=ScoutPresets, responses=_UNAVAILABLE)
def get_presets(scout: ScoutClient = Depends(get_scout_client)) -> ScoutPresets:
    """Coin chips + hip3 count from the current `scout_rows`."""
    try:
        return scout.presets()
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


# ── sim terms (v16): the board's own copy-sim terms, decoupled from Settings ──

@router.get("/sim-terms", response_model=ScoutSimTerms, responses=_UNAVAILABLE)
def get_sim_terms(scout: ScoutClient = Depends(get_scout_client)) -> ScoutSimTerms:
    """What every wallet on the Scout board is simmed at right now. The
    built-in reference (ScoutSimTerms field defaults) before anyone has ever
    called PUT."""
    try:
        return scout.sim_terms_get()
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


@router.put("/sim-terms", response_model=ScoutSimTerms, responses=_UNAVAILABLE)
def put_sim_terms(body: ScoutSimTerms, scout: ScoutClient = Depends(get_scout_client)) -> ScoutSimTerms:
    """Replace the board's sim terms. Validated by the ScoutSimTerms model
    (same field ranges as a LeaderOverride) before it ever reaches storage;
    `scout serve` re-sims from cache on its next tick (<= 10s), not here --
    this call only stores the terms and returns at once."""
    try:
        return scout.sim_terms_set(body)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


# ── custom wallets (v15): any address on the board, scored like the top 300 ──

@router.get("/custom", response_model=List[CustomWallet], responses=_UNAVAILABLE)
def list_custom(scout: ScoutClient = Depends(get_scout_client)) -> List[CustomWallet]:
    """Every wallet added by hand, with whether it is on the served board yet."""
    try:
        return scout.custom_list()
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


@router.post("/custom", response_model=CustomWallet, status_code=status.HTTP_201_CREATED,
             responses={422: {"description": "not a 0x address"}, **_UNAVAILABLE})
def add_custom(body: CustomWalletRequest, scout: ScoutClient = Depends(get_scout_client)) -> CustomWallet:
    """Add any wallet to the Scout board. It gets stats, the board's copy sim and Copy
    Fit, ranks alongside the leaderboard wallets with `custom=true`, and stays through
    refreshes until removed. The build is queued for `scout serve` (`queued`), which
    serves it even during a full refresh; poll GET /api/scout/traders/{address} (202
    while building) or the board's `preset=custom`. Idempotent."""
    try:
        out = scout.custom_add(body.address)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
    if out is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"not a 0x address: {body.address!r}")
    return out


@router.delete("/custom/{address}", status_code=status.HTTP_204_NO_CONTENT,
               responses={404: {"description": "not a custom wallet"}, **_UNAVAILABLE})
def remove_custom(address: str, scout: ScoutClient = Depends(get_scout_client)) -> Response:
    """Take a hand-added wallet off the board at once. Its cached stats stay."""
    a = valid_address(address)
    try:
        ok = scout.custom_remove(a)
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{a} is not a custom wallet")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/status", response_model=ScoutStatus, responses=_UNAVAILABLE)
def get_status(scout: ScoutClient = Depends(get_scout_client)) -> ScoutStatus:
    try:
        return scout.status()
    except ScoutUnavailable as e:
        raise _unavailable(e) from e


@router.post("/refresh", response_model=ScoutStatus,
             responses={409: {"description": "a refresh is already running"}, **_UNAVAILABLE})
def refresh(scout: ScoutClient = Depends(get_scout_client)) -> ScoutStatus:
    try:
        return scout.refresh()
    except ScoutBusy as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ScoutUnavailable as e:
        raise _unavailable(e) from e
