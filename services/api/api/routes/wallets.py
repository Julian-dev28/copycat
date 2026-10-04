"""Trade page: invest in a wallet like a perp market.

  POST /api/wallets/{address}/copy     WalletCopyRequest -> Settings (add or adjust)
  POST /api/wallets/{address}/preview  WalletCopyRequest -> WalletPreview (live reads)
  POST /api/wallets/{address}/stop     WalletStopRequest -> {settings, stopping}
  GET  /api/wallets                    WalletPosition[] (bottom table, Portfolio)

All sync `def`s: FastAPI runs them on its threadpool, so the preview's
live HL reads never block the event loop serving halt/close-all.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from contracts.models import (
    EngineStatus,
    ExposureMode,
    LeaderStatus,
    Settings,
    SizingMode,
    WalletCopyRequest,
    WalletPosition,
    WalletPreview,
    WalletStopRequest,
    norm_addr,
)

from ..config import Config
from ..deps import get_config, get_engine_client, get_store, require_auth
from ..engine_client import EngineClient, EngineUnavailable, PreviewFailed
from ..schemas import WalletStopResponse
from ..settings_store import _ADDR_RE, LeaderLimitError, SettingsStore, settings_source
from ..wallet_stop import clear_stop, is_stop_pending, request_stop

router = APIRouter(prefix="/api/wallets", tags=["wallets"], dependencies=[Depends(require_auth)])


def _addr_or_400(address: str) -> str:
    addr = norm_addr(address)
    if not _ADDR_RE.match(addr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"not a 0x address: {address!r}")
    return addr


def _target_needs_leverage(req: WalletCopyRequest) -> None:
    """Belt and braces: WalletCopyRequest's own validator already 422s this."""
    if (req.settings_source == "custom" and req.exposure_mode == ExposureMode.target
            and req.target_leverage is None):
        raise HTTPException(422, "target_leverage is required when exposure_mode is target")


@router.post("/{address}/copy", response_model=Settings)
def copy_wallet(address: str, body: WalletCopyRequest,
                store: SettingsStore = Depends(get_store),
                config: Config = Depends(get_config)) -> Settings:
    """Copy this wallet. `settings_source` global: it runs on the Settings
    tab (its override is cleared to bookkeeping only). custom: invest
    `allocation_usd` with its own terms, or adjust them. `invested_ms` is set
    when the wallet is added and kept on a re-post, so its PnL ledger carries
    on. 409 at MAX_LEADERS, 400 for a bad address or our own account, 422
    for custom without `allocation_usd` or target exposure without
    `target_leverage`. A pending stop for the wallet is cancelled: the newer
    command wins."""
    addr = _addr_or_400(address)
    _target_needs_leverage(body)
    try:
        settings = store.copy_wallet(addr, body, int(time.time() * 1000))
    except LeaderLimitError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:      # OwnAddressError is a ValueError
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    clear_stop(config.data_dir, addr)
    return settings


@router.post("/{address}/preview", response_model=WalletPreview)
def preview_wallet(address: str, body: WalletCopyRequest,
                   store: SettingsStore = Depends(get_store),
                   engine: EngineClient = Depends(get_engine_client)) -> WalletPreview:
    """What investing would copy of his book right now, sized by the same
    `engine.sizing.plan_allocation` the engine uses. 502 when his live read
    fails, 503 when the engine package is missing."""
    addr = _addr_or_400(address)
    _target_needs_leverage(body)
    try:
        return engine.preview(addr, body, store.load())
    except PreviewFailed as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


def _engine_status(engine: EngineClient) -> Optional[EngineStatus]:
    try:
        return engine.status()
    except EngineUnavailable:
        return None


@router.post("/{address}/stop", response_model=WalletStopResponse)
def stop_wallet(address: str, body: WalletStopRequest,
                store: SettingsStore = Depends(get_store),
                config: Config = Depends(get_config),
                engine: EngineClient = Depends(get_engine_client)) -> WalletStopResponse:
    """Stop copying this wallet: remove it (and its override) from settings,
    then write `data/stop/<address>.flag`. 404 when it is neither in the book
    nor an orphan we still hold copies of; 503 if that cannot be checked
    because the engine package is missing."""
    addr = _addr_or_400(address)
    in_book = addr in store.load().leaders
    if not in_book:
        st = _engine_status(engine)
        if st is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "engine status unavailable, cannot check for open copies")
        row = next((r for r in st.leaders if r.address == addr), None)
        if row is None or not (row.open_copies or row.owned_coins):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"{addr} is not in the book and has no open copies")
    settings, _ = store.stop_wallet(addr)
    request_stop(config.data_dir, addr, body.close_positions, int(time.time() * 1000))
    return WalletStopResponse(settings=settings,
                              stopping=body.close_positions and is_stop_pending(config.data_dir, addr))


def _position(addr: str, in_book: bool, row: Optional[LeaderStatus], eff: Settings,
              stopping: bool, source: str) -> WalletPosition:
    allocation = eff.sizing_mode == SizingMode.allocation
    realized = row.realized_pnl_usd if row else 0.0
    unrealized = row.unrealized_pnl_usd if row else 0.0
    pnl = realized + unrealized
    alloc_usd = eff.allocation_usd if allocation else None
    return WalletPosition(
        address=addr, in_book=in_book, settings_source=source, read_ok=bool(row and row.read_ok),
        equity_usd=row.equity_usd if row else None,
        open_copies=row.open_copies if row else 0,
        margin_used_usd=row.margin_used_usd if row else 0.0,
        exposure_usd=row.exposure_usd if row else 0.0,
        unrealized_pnl_usd=unrealized, realized_pnl_usd=realized,
        fees_usd=row.fees_usd if row else 0.0, pnl_usd=pnl,
        roe_pct=(pnl / alloc_usd * 100.0) if alloc_usd else None,
        stopping=stopping or bool(row and row.stopping),
        owned_coins=list(row.owned_coins) if row else [],
        last_read_ms=row.last_read_ms if row else None,
        sizing_mode=eff.sizing_mode,
        allocation_usd=alloc_usd,
        exposure_mode=eff.exposure_mode if allocation else None,
        target_leverage=(eff.target_leverage if allocation and eff.exposure_mode == ExposureMode.target
                         else None),
        small_account_mode=eff.small_account_mode if allocation else None,
        invested_ms=eff.invested_ms,
    )


@router.get("", response_model=List[WalletPosition])
def list_wallets(store: SettingsStore = Depends(get_store),
                 config: Config = Depends(get_config),
                 engine: EngineClient = Depends(get_engine_client)) -> List[WalletPosition]:
    """One row per wallet in the book (settings order), then every wallet
    winding down (an orphan with open copies, or a stop still pending).
    Position fields come from the engine's last cycle; if the engine
    package is missing the book rows still come back, zeroed, read_ok
    false. ROE % = (realized + unrealized) / allocation_usd x 100, None for
    a wallet that is not on allocation sizing. Terms: in-book wallets from
    settings; winding-down ones from the engine's `effective` (the terms they
    last ran with)."""
    settings = store.load()
    st = _engine_status(engine)
    rows: Dict[str, LeaderStatus] = {r.address: r for r in (st.leaders if st else [])}
    out: List[WalletPosition] = []
    for addr in settings.leaders:
        out.append(_position(addr, True, rows.get(addr), settings.for_leader(addr),
                             is_stop_pending(config.data_dir, addr),
                             settings_source(settings.leader_overrides.get(addr))))
    for addr, row in rows.items():
        if addr in settings.leaders:
            continue
        pending = is_stop_pending(config.data_dir, addr)
        if row.open_copies > 0 or row.owned_coins or row.stopping or pending:
            # winding down: custom if it ran on its own allocation terms (the engine
            # puts its last terms in `effective`), else it ran on the Settings tab
            src = ("custom" if row.effective.sizing_mode == SizingMode.allocation
                   and row.effective.invested_ms is not None else "global")
            out.append(_position(addr, False, row, row.effective, pending, src))
    return out
