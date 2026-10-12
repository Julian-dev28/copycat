"""Trade page: invest in a wallet like a perp market.

  POST /api/wallets/{address}/copy     WalletCopyRequest -> Settings (add or adjust)
  POST /api/wallets/{address}/preview  WalletCopyRequest -> WalletPreview (live reads)
  POST /api/wallets/{address}/stop     WalletStopRequest -> {settings, stopping}
  POST /api/wallets/{address}/pause    -> Settings (v8: no new opens/adds, exits mirrored)
  POST /api/wallets/{address}/resume   -> Settings
  POST /api/wallets/{address}/archive  -> WalletPosition (v8: a stopped wallet with no copies)
  GET  /api/wallets/{address}/events   EngineEvent[] (v8: that wallet's actions + skips)
  GET  /api/wallets/{address}/projection  WalletProjection, or 202 ScoutStatus (v8)
  GET  /api/wallets[?include=archived] WalletPosition[] (bottom table, Portfolio)

All sync `def`s: FastAPI runs them on its threadpool, so the preview's
live HL reads never block the event loop serving halt/close-all.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from contracts.models import (
    MAX_LEVERAGE_CAP,
    CurvePoint,
    EngineEvent,
    EngineStatus,
    ExposureMode,
    LeaderOverride,
    LeaderStatus,
    ScoutStatus,
    Settings,
    SizingMode,
    TradeDirection,
    TradingStyle,
    WalletCopyRequest,
    WalletPosition,
    WalletPreview,
    WalletProjection,
    WalletStopRequest,
    norm_addr,
)

from ..config import Config
from ..deps import get_config, get_engine_client, get_scout_client, get_store, require_auth
from ..engine_client import ArchiveRefused, EngineClient, EngineUnavailable, PreviewFailed
from ..schemas import WalletStopResponse
from ..scout_client import ScoutBusy, ScoutClient, ScoutUnavailable
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


# ── v8: pause / resume / archive ────────────────────────────────────────────

def _set_paused(address: str, paused: bool, store: SettingsStore) -> Settings:
    addr = _addr_or_400(address)
    try:
        return store.set_paused(addr, paused)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{addr} is not in the book") from e


@router.post("/{address}/pause", response_model=Settings)
def pause_wallet(address: str, store: SettingsStore = Depends(get_store)) -> Settings:
    """Pause one wallet: the engine opens and adds nothing for it (skip
    "paused"); its open copies still follow his reduces and closes. Pausing
    is not stopping: the wallet stays in the book. A global wallet gets a
    minimal override `{paused: true}` and stays "global". 404 when the wallet
    is not in the book."""
    return _set_paused(address, True, store)


@router.post("/{address}/resume", response_model=Settings)
def resume_wallet(address: str, store: SettingsStore = Depends(get_store)) -> Settings:
    """Resume a paused wallet. Moves he made while paused are not entered
    midway; the next position he opens is copied. 404 when not in the book."""
    return _set_paused(address, False, store)


def _ledgers(engine: EngineClient) -> Dict[str, Dict[str, Any]]:
    try:
        fn = getattr(engine, "wallet_ledgers", None)
        return dict(fn() or {}) if fn else {}
    except Exception:   # the list must never fail on the ledger read
        return {}


@router.post("/{address}/archive", response_model=WalletPosition,
             responses={409: {"description": "still in the book, stopping, or holding copies"}})
def archive_wallet(address: str,
                   store: SettingsStore = Depends(get_store),
                   config: Config = Depends(get_config),
                   engine: EngineClient = Depends(get_engine_client)) -> WalletPosition:
    """Archive a stopped wallet: out of the book, no stop pending, no copies.
    It leaves GET /api/wallets (see `?include=archived`) and the engine stops
    reading it. Copying it again un-archives it (a fresh investment). 409
    otherwise; 503 when the engine package is missing."""
    addr = _addr_or_400(address)
    settings = store.load()
    if addr in settings.leaders:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{addr} is in the book: stop it first")
    if is_stop_pending(config.data_dir, addr):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{addr} is still stopping")
    st = _engine_status(engine)
    if st is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "engine status unavailable, cannot check for open copies")
    row = next((r for r in st.leaders if r.address == addr), None)
    if row is not None and (row.open_copies or row.owned_coins or row.stopping):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{addr} still has copies: {', '.join(row.owned_coins) or row.open_copies}")
    try:
        led = engine.archive(addr, int(time.time() * 1000))
    except ArchiveRefused as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return _archived_position(addr, led, settings)


# ── v8: one wallet's history and projection ─────────────────────────────────

EVENTS_MAX_LIMIT = 500


@router.get("/{address}/events", response_model=List[EngineEvent])
def wallet_events(address: str,
                  limit: int = Query(50, ge=1, le=EVENTS_MAX_LIMIT),
                  before_ms: Optional[int] = Query(None, ge=0),
                  engine: EngineClient = Depends(get_engine_client)) -> List[EngineEvent]:
    """This wallet's engine events, newest first: opens/adds/reduces/closes
    and skips with their reason ("paused", "filtered: BTC", "worse than
    entry"...). Page with `before_ms` = the last row's ts_ms. Read from the
    tail of events.jsonl with a capped scan, so an old wallet in a big log
    may return fewer rows than exist. 503 when the engine package is missing."""
    addr = _addr_or_400(address)
    try:
        return engine.leader_events(addr, limit, before_ms)
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


@router.get("/{address}/projection", response_model=WalletProjection,
            responses={202: {"model": ScoutStatus, "description": "no cached data yet; a build is queued"},
                       409: {"description": "a what-if is already running"}})
def wallet_projection(request: Request, address: str,
                      allocation_usd: float = Query(1000.0, gt=0),
                      trade_direction: Optional[TradeDirection] = Query(None),
                      exposure_mode: Optional[ExposureMode] = Query(None),
                      target_leverage: Optional[int] = Query(None, ge=1, le=MAX_LEVERAGE_CAP),
                      store: SettingsStore = Depends(get_store),
                      scout: ScoutClient = Depends(get_scout_client)) -> Any:
    """His last 30d replayed onto `allocation_usd` at these terms (counter =
    every side inverted, liquidations on our side), by discovery's copy-sim
    on CACHED fills and candles only: no HL call in this request. Unset terms
    come from the wallet's current settings (custom override, else the
    Settings tab), and his coin filters apply. No cached data for him yet:
    202 with the Scout status, and a build is queued (as GET
    /api/scout/traders/{a} does). 409 while another what-if runs."""
    addr = _addr_or_400(address)
    settings = store.load()
    lock = request.app.state.scout_what_if_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "a what-if is already running")
    try:
        return build_projection(scout, addr, settings, allocation_usd, trade_direction,
                                exposure_mode, target_leverage)
    except LookupError:
        return _queue_build(scout, addr)
    except ScoutBusy as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ScoutUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    finally:
        lock.release()


def build_projection(scout: ScoutClient, addr: str, settings: Settings, allocation_usd: float,
                     trade_direction: Optional[TradeDirection] = None,
                     exposure_mode: Optional[ExposureMode] = None,
                     target_leverage: Optional[int] = None,
                     copy_request: Optional[WalletCopyRequest] = None) -> WalletProjection:
    """The projection itself, shared with the MCP copy plan (api.mcp_plans).
    Unset terms come from the wallet's current settings. `copy_request`: the
    exact Trade-ticket terms a plan writes; every field it sets (leverage
    mode, leverage, margin mode, entry deviation, small-account mode, coin
    lists) is replayed too, so the projection runs at the plan's terms.
    Regression: the MCP plan's projection used only direction / exposure /
    target leverage, so a "follow his leverage, 2% entry" plan was replayed at
    the saved leverage_mode (max) and 10% entry. Raises LookupError (no
    cached data), ScoutBusy, ScoutUnavailable; the caller holds the what-if
    lock."""
    eff = settings.for_leader(addr)
    direction = trade_direction or eff.trade_direction
    extra: Dict[str, Any] = {}
    if copy_request is not None:
        for k in ("margin_mode", "max_worse_entry_pct", "small_account_mode", "leverage_mode", "leverage",
                  "coin_allowlist", "coin_blocklist"):
            v = getattr(copy_request, k)
            if v is not None:
                extra[k] = v
    patch = LeaderOverride(sizing_mode=SizingMode.allocation, allocation_usd=allocation_usd,
                           trade_direction=direction,
                           exposure_mode=exposure_mode or eff.exposure_mode,
                           target_leverage=target_leverage or eff.target_leverage, **extra)
    res = scout.what_if(addr, settings, allocation_usd, patch)
    sc = res.score
    note = "his last 30 days on cached data"
    if direction == TradeDirection.counter:
        note += "; counter: every side inverted"
    if eff.coin_allowlist or eff.coin_blocklist:
        note += "; coin filters applied"
    return WalletProjection(
        address=addr, allocation_usd=allocation_usd, trade_direction=direction,
        curve=[CurvePoint(t_ms=p.t_ms, value=p.value) for p in res.sim_curve],
        return_pct=sc.sim_return_pct, max_drawdown_pct=sc.sim_max_drawdown_pct,
        liquidations=sc.sim_liquidations, copies=sc.sim_copies,
        skipped=sc.sim_skipped_min_order, note=note)


def _queue_build(scout: ScoutClient, addr: str) -> Any:
    """No Scout data for him: `profile` queues the build (never builds here)."""
    try:
        out = scout.profile(addr)
    except ScoutUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no Scout data for {addr}")
    if not isinstance(out, ScoutStatus):   # a profile without sim inputs yet: still building
        out = ScoutStatus(refresh_id=None, state="running", stage="stats", done=0, total=1)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=out.model_dump(mode="json"))


# ── the list ────────────────────────────────────────────────────────────────

_STYLE_TTL_S = 300.0


def _styles(request: Request, scout: Optional[ScoutClient], addrs: List[str]) -> Dict[str, TradingStyle]:
    """His Scout style per wallet, from the stored board row (one indexed
    page query per wallet, cached 5 min on the app). Never raises; unknown =
    absent. Never queues a build (profile would)."""
    if scout is None or not addrs:
        return {}
    cache = getattr(request.app.state, "wallet_style_cache", None)
    if cache is None:
        cache = {}
        request.app.state.wallet_style_cache = cache
    now = time.monotonic()
    out: Dict[str, TradingStyle] = {}
    for a in addrs:
        hit = cache.get(a)
        if hit is None or now - hit[0] > _STYLE_TTL_S:
            style = None
            try:
                page = scout.page({"q": a, "limit": 1})
                row = next((r for r in page.rows if norm_addr(r.address) == a), None)
                style = row.style if row is not None else None
            except Exception:
                style = None
            hit = (now, style)
            cache[a] = hit
        if hit[1] is not None:
            out[a] = hit[1]
    return out


def _terms_settings(base: Settings, terms: Dict[str, Any]) -> Settings:
    """The book-wide settings with a wallet's last terms from its ledger."""
    data = base.model_dump(mode="json")
    data.update({k: v for k, v in (terms or {}).items() if v is not None})
    data["leader_overrides"] = {}
    try:
        return Settings.model_validate(data)
    except Exception:
        return base


def _position(addr: str, in_book: bool, row: Optional[LeaderStatus], eff: Settings,
              stopping: bool, source: str, status_: str,
              led: Optional[Dict[str, Any]] = None,
              style: Optional[TradingStyle] = None) -> WalletPosition:
    allocation = eff.sizing_mode == SizingMode.allocation
    led = led or {}
    realized = row.realized_pnl_usd if row else float(led.get("realized_pnl_usd") or 0.0)
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
        fees_usd=row.fees_usd if row else float(led.get("fees_usd") or 0.0), pnl_usd=pnl,
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
        status=status_,
        trade_direction=eff.trade_direction,
        coin_allowlist=list(eff.coin_allowlist), coin_blocklist=list(eff.coin_blocklist),
        style=style,
        archived_ms=led.get("archived_ms") if status_ == "archived" else None,
        one_shot=bool(eff.one_shot),
    )


def _archived_position(addr: str, led: Dict[str, Any], settings: Settings,
                       style: Optional[TradingStyle] = None) -> WalletPosition:
    terms = led.get("terms") or {}
    eff = _terms_settings(settings, terms)
    src = ("custom" if eff.sizing_mode == SizingMode.allocation and eff.invested_ms is not None
           else "global")
    return _position(addr, False, None, eff, False, src, "archived", led, style)


def wallet_status(in_book: bool, paused: bool, stopping: bool, archived: bool) -> str:
    """WalletPosition.status (v8). In the book: running, or paused. A pending
    stop (or a close still retrying): stopping. Out of the book: stopped
    (copies winding down, or a history row not archived yet), or archived."""
    if stopping:
        return "stopping"
    if in_book:
        return "paused" if paused else "running"
    return "archived" if archived else "stopped"


@router.get("", response_model=List[WalletPosition])
def list_wallets(request: Request,
                 include: Optional[str] = Query(None, pattern="^archived$"),
                 store: SettingsStore = Depends(get_store),
                 config: Config = Depends(get_config),
                 engine: EngineClient = Depends(get_engine_client),
                 scout: ScoutClient = Depends(get_scout_client)) -> List[WalletPosition]:
    """One row per wallet in the book (settings order), then every wallet
    out of the book: winding down (an orphan with open copies, or a stop
    still pending) or stopped with a PnL history (a ledger row) and not
    archived yet. `include=archived` also returns archived wallets (from the
    ledger: realized PnL and their last terms). Position fields come from the
    engine's last cycle; if the engine package is missing the book rows still
    come back, zeroed, read_ok false. ROE % = (realized + unrealized) /
    allocation_usd x 100, None for a wallet not on allocation sizing. Terms:
    in-book wallets from settings; out-of-book ones from the engine's
    `effective` (the terms they last ran with). `style` is his Scout style
    when Scout has his board row, else null."""
    settings = store.load()
    st = _engine_status(engine)
    rows: Dict[str, LeaderStatus] = {r.address: r for r in (st.leaders if st else [])}
    ledgers = _ledgers(engine)
    out: List[WalletPosition] = []
    for addr in settings.leaders:
        eff = settings.for_leader(addr)
        pending = is_stop_pending(config.data_dir, addr)
        row = rows.get(addr)
        out.append(_position(addr, True, row, eff, pending,
                             settings_source(settings.leader_overrides.get(addr)),
                             wallet_status(True, eff.paused, pending, False),
                             ledgers.get(addr)))
    listed = set(settings.leaders)
    for addr, row in rows.items():
        if addr in listed:
            continue
        pending = is_stop_pending(config.data_dir, addr)
        led = ledgers.get(addr) or {}
        winding = bool(row.open_copies > 0 or row.owned_coins or row.stopping or pending)
        archived = bool(led.get("archived_ms")) and not winding
        if not winding and not led:
            continue
        if archived and include != "archived":
            continue
        listed.add(addr)
        if archived:
            out.append(_archived_position(addr, led, settings))
            continue
        # custom if it ran on its own allocation terms (the engine puts its last
        # terms in `effective`), else it ran on the Settings tab
        src = ("custom" if row.effective.sizing_mode == SizingMode.allocation
               and row.effective.invested_ms is not None else "global")
        out.append(_position(addr, False, row, row.effective, pending, src,
                             wallet_status(False, False, pending or row.stopping, False), led))
    if include == "archived":
        for addr, led in sorted(ledgers.items(), key=lambda kv: -(kv[1].get("archived_ms") or 0)):
            if addr not in listed and led.get("archived_ms"):
                out.append(_archived_position(addr, led, settings))
    styles = _styles(request, scout, [w.address for w in out])
    for w in out:
        w.style = styles.get(w.address)
    return out
