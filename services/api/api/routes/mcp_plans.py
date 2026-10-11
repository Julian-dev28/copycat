"""MCP copy plans (contract v9), the "thesis + trade" flow of the copycat MCP server.

  POST /api/mcp/plans                 CopyPlanRequest -> CopyPlan (read-only: preview,
                                      cached projection, warnings; stored 120 s)
  POST /api/mcp/plans/{id}/execute    CopyPlanExecuteRequest -> CopyPlanResult

Execute writes the plan's custom terms through `SettingsStore.copy_wallet`
(the same write as POST /api/wallets/{a}/copy); the engine places orders on its
next cycle if, and only if, the user has trading on. Guards and files: see
api.mcp_plans. Sync `def`s: the preview's live HL reads run on the threadpool.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from contracts.models import (
    CopyPlan,
    CopyPlanExecuteRequest,
    CopyPlanRequest,
    CopyPlanResult,
    TraderProfile,
    TradingStyle,
    WalletPosition,
    WalletProjection,
    norm_addr,
)

from .. import mcp_plans as mp
from ..config import Config
from ..deps import get_config, get_engine_client, get_scout_client, get_store, require_auth
from ..engine_client import EngineClient, EngineUnavailable, PreviewFailed
from ..scout_client import ScoutClient
from ..settings_store import LeaderLimitError, SettingsStore, settings_source
from ..wallet_stop import clear_stop
from . import wallets as wallet_routes

router = APIRouter(prefix="/api/mcp", tags=["mcp"], dependencies=[Depends(require_auth)])


def get_plan_store(request: Request) -> mp.PlanStore:
    st = getattr(request.app.state, "mcp_plan_store", None)
    if st is None:
        st = mp.PlanStore(request.app.state.config.data_dir)
        request.app.state.mcp_plan_store = st
    return st


def _preview(engine: EngineClient, store: SettingsStore, addr: str, req):
    try:
        return engine.preview(addr, req, store.load())
    except PreviewFailed as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


def _book(engine: EngineClient, addr: str):
    try:
        return engine.leader_book(addr)
    except PreviewFailed as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


def _projection(request: Request, scout: ScoutClient, addr: str, settings, body: CopyPlanRequest,
                creq) -> Optional[WalletProjection]:
    """Cached data only, never waits: None when there is none yet, Scout is
    busy or down, or another what-if holds the lock."""
    lock = request.app.state.scout_what_if_lock
    if not lock.acquire(blocking=False):
        return None
    try:
        return wallet_routes.build_projection(scout, addr, settings, body.amount_usd,
                                              body.trade_direction, creq.exposure_mode,
                                              creq.target_leverage)
    except Exception:
        return None
    finally:
        lock.release()


def _style(scout: ScoutClient, addr: str) -> Optional[TradingStyle]:
    try:
        page = scout.page({"q": addr, "limit": 1})
        row = next((r for r in page.rows if norm_addr(r.address) == addr), None)
        return row.style if row is not None else None
    except Exception:
        return None


def _his_liq_pct(scout: ScoutClient, addr: str) -> Optional[float]:
    """His nearest liquidation from the Scout profile (queues a build if he
    has none, which the projection then uses next time)."""
    try:
        prof = scout.profile(addr)
    except Exception:
        return None
    return prof.account.nearest_liq_pct if isinstance(prof, TraderProfile) else None


@router.post("/plans", response_model=CopyPlan)
def create_plan(request: Request, body: CopyPlanRequest,
                store: SettingsStore = Depends(get_store),
                engine: EngineClient = Depends(get_engine_client),
                scout: ScoutClient = Depends(get_scout_client),
                plans: mp.PlanStore = Depends(get_plan_store)) -> CopyPlan:
    """Build a copy plan for `address` at `amount_usd`: the engine's own
    preview at these custom terms, the cached 30-day projection if any, and
    the warnings to read before approving. Read-only on the book: stored
    for 120 s, used once by execute. 502/503 when the live preview fails."""
    addr = body.address
    creq = mp.copy_request_for(body)
    preview = _preview(engine, store, addr, creq)
    book = _book(engine, addr)        # after the preview: the plan never predates what it shows
    settings = store.load()
    projection = _projection(request, scout, addr, settings, body, creq)
    own = addr in store.own_addresses()
    warnings, executable = mp.plan_warnings(
        body, preview, projection, settings, _style(scout, addr), _his_liq_pct(scout, addr),
        own, mp.trading_allowed(), mp.max_usd())
    plan = mp.new_plan(body, preview, projection, settings, warnings, executable, plans.now_ms(),
                       book)
    plans.put(plan)
    plans.audit("plan", plan_id=plan.plan_id, outcome="created", executable=executable,
                trading_live=plan.trading_live, book_fingerprint=plan.book_fingerprint,
                positions=len(preview.slices), copied=preview.copied, **mp.audit_terms(body))
    return plan


@router.post("/plans/{plan_id}/execute", response_model=CopyPlanResult,
             responses={403: {"description": "disabled, wrong confirm code, or over a cap"},
                        404: {"description": "unknown plan"},
                        409: {"description": "his book changed, or your book is full"},
                        410: {"description": "plan expired or already used"},
                        429: {"description": "rate limit"}})
def execute_plan(plan_id: str, body: CopyPlanExecuteRequest,
                 store: SettingsStore = Depends(get_store),
                 config: Config = Depends(get_config),
                 engine: EngineClient = Depends(get_engine_client),
                 plans: mp.PlanStore = Depends(get_plan_store)) -> CopyPlanResult:
    """Apply a plan: guards (a)-(f) in api.mcp_plans, then the plan's custom
    terms through the Trade page's copy write. Never changes `enabled` or
    `dry_run`; with trading off nothing is ordered."""
    if not mp.trading_allowed():
        plans.audit("execute", plan_id=plan_id, outcome="disabled", status=403)
        raise HTTPException(status.HTTP_403_FORBIDDEN, mp.ENABLE_HINT)
    if plans.executes_in_window() >= mp.RATE_LIMIT:
        plans.audit("execute", plan_id=plan_id, outcome="rate_limited", status=429)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"at most {mp.RATE_LIMIT} plan executes per hour; try again later")
    with plans.locked():
        found = plans.get(plan_id)
        plan = found[0] if found else None
        terms = mp.audit_terms(plan.request) if plan else {}
        try:
            plan, bad = mp.check_plan(found, plan_id, body.confirm_code, plans.now_ms())
            settings = store.load()
            mp.check_caps(plan, settings, mp.max_usd())
            addr = plan.request.address
            now_fp, _ = mp.book_fingerprint(_book(engine, addr), mp.planned_coins(plan.preview))
            if now_fp != plan.book_fingerprint:
                raise mp.PlanRefused(409, "book_changed", "the positions this plan copies changed since "
                                                          "it was made: make a new plan with copy_plan",
                                     burn=True)
            mp.check_book_room(plan, store.load())
        except mp.PlanRefused as e:
            if plan is not None and (e.outcome == "bad_code" or e.burn):
                p2, b2 = found
                if e.outcome == "bad_code":
                    b2 += 1
                if e.burn:
                    p2 = p2.model_copy(update={"used_ms": plans.now_ms()})
                plans.update(p2, b2)
            plans.audit("execute", plan_id=plan_id, outcome=e.outcome, status=e.status, **terms)
            raise HTTPException(e.status, e.detail) from e
        except HTTPException as e:
            plans.audit("execute", plan_id=plan_id, outcome="preview_failed", status=e.status_code,
                        **terms)
            raise
        now_ms = plans.now_ms()
        try:
            new_settings = store.copy_wallet(addr, plan.copy_request, now_ms)
        except LeaderLimitError as e:
            plans.audit("execute", plan_id=plan_id, outcome="book_full", status=409, **terms)
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        except ValueError as e:
            plans.audit("execute", plan_id=plan_id, outcome="refused", status=400, **terms)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        plans.update(plan.model_copy(update={"used_ms": now_ms}), bad)
        clear_stop(config.data_dir, addr)
        live = bool(new_settings.enabled and not new_settings.dry_run)
        plans.audit("execute", plan_id=plan_id, outcome="executed", status=200,
                    trading_live=live, **terms)
    return CopyPlanResult(
        executed=True, plan_id=plan.plan_id, address=addr, one_shot=not plan.request.follow,
        trading_live=live, wallet=_wallet_row(addr, new_settings, engine),
        note=_note(plan, live))


def _wallet_row(addr: str, settings, engine: EngineClient) -> Optional[WalletPosition]:
    try:
        eff = settings.for_leader(addr)
        st = wallet_routes._engine_status(engine)
        row = next((r for r in (st.leaders if st else []) if r.address == addr), None)
        return wallet_routes._position(
            addr, True, row, eff, False, settings_source(settings.leader_overrides.get(addr)),
            wallet_routes.wallet_status(True, eff.paused, False, False))
    except Exception:   # the copy is written; a display row must not fail the response
        return None


def _note(plan: CopyPlan, live: bool) -> str:
    r = plan.request
    lev = f"{r.leverage}x" if r.leverage else "his leverage"
    what = ("copies his current positions once, then only mirrors his exits (one-shot)"
            if not r.follow else "copies his current and future positions")
    head = (f"Saved: ${r.amount_usd:,.2f} on {r.address}, {r.trade_direction.value}, {lev}, "
            f"entries within {r.entry_deviation_pct:g}% of his; {what}. ")
    if live:
        return head + ("Trading is live: the engine places the orders on its next cycle (seconds). "
                       "Check my_wallets / engine_status, or the Trade page.")
    return head + ("Trading is NOT live (enabled=false or dry_run=true): nothing is ordered until "
                   "the user turns trading on in the copycat web UI.")

