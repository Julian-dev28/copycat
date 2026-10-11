"""MCP copy plans: "paste an address, see his strategy at $X, approve, copy".

The copycat MCP server (services/mcp) lets the user's own Claude Code build a
plan and, only when the operator opted in, execute it. Execution never talks
to Hyperliquid from here: it writes the same per-wallet terms the Trade page
writes (`SettingsStore.copy_wallet`), and the engine, the one owner of orders
and positions, does the trading on its next cycle.

Files (all under the data dir, 0600, written atomically under an flock):
  mcp_plans.json   plan_id -> stored plan (pruned PRUNE_GRACE_S after expiry)
  mcp_audit.jsonl  one line per plan and per execute attempt, never a secret
                   (no confirm code, no token, no key)

Execute guards, in this order (each one audit-logged with its outcome):
  (a) COPYCAT_MCP_ALLOW_TRADING=1 in the api's env, else 403
      rate limit: RATE_LIMIT executes per hour (from the audit log), else 429
  (b) the plan exists (404), is not used and not expired (410)
  (c) the confirm code matches, constant-time (403); MAX_BAD_CODES wrong
      codes burn the plan
  (d) amount_usd <= COPYCAT_MCP_MAX_USD (default 100) and leverage <=
      settings.max_position_leverage (403)
  (e) his positions now (one account read, `leader_book`) hash to the plan's
      book_fingerprint (409, plan burned)
  (f) the book has room (MAX_LEADERS) unless he is already in it (409)
Then `copy_wallet` with the plan's custom terms. `enabled` and `dry_run` are
never touched: whether anything is ordered stays the user's switch.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from contracts.models import (
    HL_MIN_ORDER_USD,
    MAX_LEADERS,
    MCP_CONFIRM_CODE_LEN,
    MCP_PLAN_TTL_S,
    CopyPlan,
    CopyPlanRequest,
    ExposureMode,
    LeverageMode,
    Settings,
    TradingStyle,
    WalletCopyRequest,
    WalletPreview,
    WalletProjection,
)

PLANS_FILE = "mcp_plans.json"
AUDIT_FILE = "mcp_audit.jsonl"
ALLOW_ENV = "COPYCAT_MCP_ALLOW_TRADING"
MAX_USD_ENV = "COPYCAT_MCP_MAX_USD"
DEFAULT_MAX_USD = 100.0
RATE_LIMIT = 10                 # executes per RATE_WINDOW_S
RATE_WINDOW_S = 3600
MAX_BAD_CODES = 3               # wrong confirm codes before the plan is burned
PRUNE_GRACE_S = 600             # expired plans linger this long so execute says "expired", not "unknown"
LIQ_WARN_PCT = 5.0
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: read aloud, typed back
ENABLE_HINT = (f"Execution from Claude Code is off. To allow it, the operator sets {ALLOW_ENV}=1 in "
               f"the copycat api's environment (or .env) and restarts the api, and sets the same "
               f"variable in the MCP server's env (claude mcp add ... -e {ALLOW_ENV}=1). "
               f"{MAX_USD_ENV} caps the amount per plan (default ${DEFAULT_MAX_USD:.0f}).")


class PlanRefused(Exception):
    """A guard said no. `status` is the HTTP code, `outcome` the audit word."""

    def __init__(self, status: int, outcome: str, detail: str, burn: bool = False):
        super().__init__(detail)
        self.status = status
        self.outcome = outcome
        self.detail = detail
        self.burn = burn


# ── env policy ────────────────────────────────────────────────────────────

def trading_allowed(environ: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get(ALLOW_ENV) or "").strip() == "1"


def max_usd(environ: Optional[Dict[str, str]] = None) -> float:
    env = os.environ if environ is None else environ
    raw = (env.get(MAX_USD_ENV) or "").strip()
    try:
        v = float(raw) if raw else DEFAULT_MAX_USD
    except ValueError:
        return DEFAULT_MAX_USD
    return v if v > 0 else DEFAULT_MAX_USD


# ── pure helpers ──────────────────────────────────────────────────────────

def copy_request_for(req: CopyPlanRequest) -> WalletCopyRequest:
    """The Trade-page terms a plan writes. leverage None follows his: exposure
    match (his book at his leverage) with leverage_mode match. leverage L:
    exposure target at L (allocation x L in his proportions)."""
    lev = req.leverage
    return WalletCopyRequest(
        settings_source="custom", allocation_usd=req.amount_usd,
        exposure_mode=ExposureMode.target if lev else ExposureMode.match,
        target_leverage=lev,
        leverage_mode=None if lev else LeverageMode.match,
        max_worse_entry_pct=req.entry_deviation_pct,
        trade_direction=req.trade_direction,
        only_new_positions=False,
        one_shot=not req.follow,
    )


def planned_coins(preview: WalletPreview) -> List[str]:
    """Coins the plan would actually open (not skipped)."""
    return sorted({s.coin for s in preview.slices if s.status != "skip"})


def book_fingerprint(book: List[Dict[str, Any]],
                     coins: Optional[List[str]] = None) -> Tuple[str, List[str]]:
    """sha256 over his positions (coin, side, |size| x entry to the cent),
    sorted by coin, plus a human summary sorted by size. `book` is
    `engine.public.leader_book` (one account read). Entry-based, so a mark
    move does not change it; an open, add, reduce, close or flip does.

    `coins`: hash only these (the ones the plan copies), plus whether each is
    still held. A very active trader changing a coin we are NOT copying no
    longer voids the plan; any change to a planned coin (size, side, closed)
    still does. The summary always covers his whole book."""
    all_rows = sorted((str(b["coin"]), str(b["side"]), round(float(b["notional_usd"]), 2)) for b in book)
    if coins is None:
        rows = all_rows
    else:
        held = {r[0]: r for r in all_rows}
        rows = [held.get(c, (c, "flat", 0.0)) for c in sorted(set(coins))]
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    summary = [f"{c} {side} ${n:,.0f}" for c, side, n in sorted(all_rows, key=lambda r: -r[2])]
    return digest, summary


def new_confirm_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(MCP_CONFIRM_CODE_LEN))


def codes_match(given: str, expected: str) -> bool:
    g = (given or "").strip().upper().encode()
    return hmac.compare_digest(g, expected.encode())


def plan_warnings(req: CopyPlanRequest, preview: WalletPreview,
                  projection: Optional[WalletProjection], settings: Settings,
                  style: Optional[TradingStyle], his_liq_pct: Optional[float],
                  own: bool, allowed: bool, cap_usd: float) -> Tuple[List[str], bool]:
    """Everything the user should read before saying yes, and whether a guard
    will refuse the plan outright (`executable` false)."""
    w: List[str] = []
    executable = True
    live = settings.enabled and not settings.dry_run
    addr = req.address
    if not allowed:
        executable = False
        w.append("Execution is disabled: " + ENABLE_HINT)
    if req.amount_usd > cap_usd:
        executable = False
        w.append(f"${req.amount_usd:,.2f} is over the per-plan cap of ${cap_usd:,.2f} "
                 f"({MAX_USD_ENV}); execute will refuse it. Make a plan at or under the cap.")
    if req.leverage is not None and req.leverage > settings.max_position_leverage:
        executable = False
        w.append(f"{req.leverage}x is over your max position leverage "
                 f"({settings.max_position_leverage}x, Settings tab); execute will refuse it.")
    if own:
        executable = False
        w.append(f"{addr} is one of this copycat's own accounts; it cannot be copied.")
    in_book = addr in settings.leaders
    if not in_book and len(settings.leaders) >= MAX_LEADERS:
        executable = False
        w.append(f"Your book is full ({MAX_LEADERS} wallets); stop one in the web UI first.")
    if in_book:
        w.append("He is already in your book: executing replaces this wallet's terms "
                 "(his ledger carries on). Positions you already copy are kept.")
        if settings.for_leader(addr).paused:
            w.append("This wallet is paused: executing keeps it paused (resume it on the Trade page).")
        w.append("Already in the book, so the engine has seen his current positions: they are "
                 "not entered midway; only his next moves are copied.")
    if not live:
        w.append("Trading is not live (enabled=false or dry_run=true): executing only saves the "
                 "copy terms and nothing is ordered; positions he opens while it is off are not "
                 "entered later. Only you can turn trading on, in the copycat web UI.")
        if not req.follow:
            w.append("One-shot while trading is off copies nothing: his current positions are "
                     "seen (and skipped) now, and nothing after them is copied.")
    if style == TradingStyle.algo:
        w.append("Scout tags him as an algo/HFT trader: copies land seconds late, which usually "
                 "erases a short-hold edge.")
    elif style == TradingStyle.scalp:
        w.append("Scout tags him as a scalper: short holds degrade most when copied seconds late.")
    if his_liq_pct is not None and his_liq_pct < LIQ_WARN_PCT:
        w.append(f"His nearest liquidation is {his_liq_pct:.1f}% away: a small move against him "
                 f"liquidates that position (and your copy at the same leverage).")
    hot = sorted({s.leverage for s in preview.slices if s.status != "skip" and s.leverage > 0
                  and 100.0 / s.leverage < LIQ_WARN_PCT})
    if hot:
        w.append(f"Copies at {', '.join(f'{x}x' for x in hot)} liquidate on roughly a "
                 f"{100.0 / max(hot):.1f}% adverse move or less (isolated margin, before "
                 f"maintenance margin).")
    if not preview.slices:
        w.append("He holds no positions right now." + (
            " One-shot would copy nothing." if not req.follow else
            " Nothing opens until his next position."))
    under_min = [s for s in preview.slices if s.status == "skip"
                 and "minimum" in (s.reason or "")]
    if under_min:
        w.append(f"{len(under_min)} of his {len(preview.slices)} positions are under the "
                 f"${HL_MIN_ORDER_USD} order minimum at ${req.amount_usd:,.2f} and are skipped: "
                 + ", ".join(s.coin for s in under_min)
                 + (f". ${preview.min_allocation_for_full_book:,.2f} copies his full book."
                    if preview.min_allocation_for_full_book else "."))
    other = [s for s in preview.slices if s.status == "skip" and s not in under_min]
    if other:
        w.append("Also skipped: " + "; ".join(f"{s.coin} ({s.reason})" for s in other))
    if preview.copied == 0 and preview.slices:
        w.append("At this amount none of his current positions would be copied.")
    if projection is None:
        w.append("No cached 30-day projection for him yet (Scout is building it).")
    elif projection.liquidations:
        w.append(f"The 30-day replay at these terms hit {projection.liquidations} liquidation(s).")
    if req.trade_direction.value == "counter":
        w.append("Counter: you take the opposite side of every position he opens.")
    w.append(f"Entries wait while price is more than {req.entry_deviation_pct:g}% worse than his "
             f"entry and fill if it comes back (re-checked every cycle).")
    w.extend(preview.notes)
    return w, executable


# ── storage ──────────────────────────────────────────────────────────────

def _write_atomic_0600(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PlanStore:
    """Plans and the audit log. One flock serializes every read-modify-write,
    so execute is single-use even with two concurrent requests."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / PLANS_FILE
        self.audit_path = self.data_dir / AUDIT_FILE
        self.lock_path = self.data_dir / (PLANS_FILE + ".lock")
        self.clock = clock

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, plans: Dict[str, Dict[str, Any]]) -> None:
        now = self.now_ms()
        keep = {k: v for k, v in plans.items()
                if int(v.get("plan", {}).get("expires_ms") or 0) + PRUNE_GRACE_S * 1000 > now}
        _write_atomic_0600(self.path, json.dumps(keep, indent=1, sort_keys=True) + "\n")

    def put(self, plan: CopyPlan) -> None:
        with self.locked():
            plans = self._load()
            plans[plan.plan_id] = {"plan": plan.model_dump(mode="json"), "bad_codes": 0}
            self._save(plans)

    def get(self, plan_id: str) -> Optional[Tuple[CopyPlan, int]]:
        rec = self._load().get(plan_id)
        if not rec:
            return None
        return CopyPlan.model_validate(rec["plan"]), int(rec.get("bad_codes") or 0)

    def update(self, plan: CopyPlan, bad_codes: int) -> None:
        """Caller holds `locked()`."""
        plans = self._load()
        plans[plan.plan_id] = {"plan": plan.model_dump(mode="json"), "bad_codes": bad_codes}
        self._save(plans)

    # audit

    def audit(self, event: str, **fields: Any) -> None:
        """Append one line. Callers pass only plan terms and outcomes: never
        the confirm code, a token or a key (a gate test greps the file)."""
        line = {"ts_ms": self.now_ms(), "event": event, **fields}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(line, sort_keys=True) + "\n").encode())
        finally:
            os.close(fd)

    def executes_in_window(self) -> int:
        """Execute attempts in the last RATE_WINDOW_S that reached a plan
        (everything but "disabled" and "rate_limited")."""
        since = self.now_ms() - RATE_WINDOW_S * 1000
        n = 0
        try:
            with self.audit_path.open("r", encoding="utf-8") as f:
                for raw in f:
                    try:
                        e = json.loads(raw)
                    except ValueError:
                        continue
                    if (e.get("event") == "execute" and int(e.get("ts_ms") or 0) >= since
                            and e.get("outcome") not in ("disabled", "rate_limited")):
                        n += 1
        except OSError:
            return 0
        return n


def audit_terms(req: CopyPlanRequest) -> Dict[str, Any]:
    return {"address": req.address, "amount_usd": req.amount_usd, "leverage": req.leverage,
            "entry_deviation_pct": req.entry_deviation_pct,
            "trade_direction": req.trade_direction.value, "follow": req.follow}


def new_plan(req: CopyPlanRequest, preview: WalletPreview, projection: Optional[WalletProjection],
             settings: Settings, warnings: List[str], executable: bool, now_ms: int,
             book: List[Dict[str, Any]]) -> CopyPlan:
    fp, summary = book_fingerprint(book, planned_coins(preview))
    return CopyPlan(
        plan_id="plan_" + secrets.token_hex(8), confirm_code=new_confirm_code(),
        created_ms=now_ms, expires_ms=now_ms + MCP_PLAN_TTL_S * 1000,
        request=req, copy_request=copy_request_for(req), preview=preview, projection=projection,
        trading_live=bool(settings.enabled and not settings.dry_run),
        executable=executable, warnings=warnings, book_fingerprint=fp, book_summary=summary)


def check_plan(found: Optional[Tuple[CopyPlan, int]], plan_id: str, code: str,
               now_ms: int) -> Tuple[CopyPlan, int]:
    """Guards (b) and (c). Raises PlanRefused; a wrong code bumps the count
    (the caller persists it) and the MAX_BAD_CODES-th burns the plan."""
    if found is None:
        raise PlanRefused(404, "unknown_plan", f"no plan {plan_id!r} (unknown or pruned): make a new "
                                               f"plan with copy_plan")
    plan, bad = found
    if plan.used_ms is not None:
        raise PlanRefused(410, "used", "this plan was already used (plans are single-use): make a "
                                       "new plan with copy_plan")
    if now_ms >= plan.expires_ms:
        raise PlanRefused(410, "expired", f"this plan expired ({MCP_PLAN_TTL_S}s after it was made): "
                                          f"make a new plan with copy_plan")
    if not codes_match(code, plan.confirm_code):
        bad += 1
        burn = bad >= MAX_BAD_CODES
        raise PlanRefused(403, "bad_code",
                          "confirm code does not match this plan"
                          + (f"; {MAX_BAD_CODES} wrong codes, the plan is void: make a new one"
                             if burn else ""), burn=burn)
    return plan, bad


def check_caps(plan: CopyPlan, settings: Settings, cap_usd: float) -> None:
    """Guard (d)."""
    req = plan.request
    if req.amount_usd > cap_usd:
        raise PlanRefused(403, "over_cap", f"${req.amount_usd:,.2f} is over the per-plan cap "
                                           f"${cap_usd:,.2f} ({MAX_USD_ENV})")
    if req.leverage is not None and req.leverage > settings.max_position_leverage:
        raise PlanRefused(403, "over_leverage", f"{req.leverage}x is over max_position_leverage "
                                                f"{settings.max_position_leverage}x")


def check_book_room(plan: CopyPlan, settings: Settings) -> None:
    """Guard (f)."""
    if plan.request.address not in settings.leaders and len(settings.leaders) >= MAX_LEADERS:
        raise PlanRefused(409, "book_full", f"your book is full ({MAX_LEADERS} wallets): stop one "
                                            f"in the web UI first")
