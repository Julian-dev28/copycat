"""Regression tests for docs/audit/AUDIT_2026-10.md blockers B1 and B2.

B1: a fresh copy on a HIP-3 dex was invisible to our own account reads (the
active-dex cache skips that dex for up to 300 s), so two cycles later the
engine deleted it as "vanished" and the real position was never managed again.

B2: writes re-resolved the active account on every call, so switching accounts
mid-cycle could send account A's planned orders to account B.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine import core
from engine.state import Copy
from engine_fakes import LEADER1, OUR, FakeVenue

from contracts.models import Settings


def cfg(**kw) -> Settings:
    base = dict(enabled=True, dry_run=False, leaders=[LEADER1], sizing_mode="fixed_notional",
                fixed_notional_usd=20.0, max_worse_entry_pct=100.0)
    base.update(kw)
    return Settings(**base)


def run(venue, settings, state, now_ms=0, creds=None, switched_in=False):
    events: List[Any] = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append, creds=creds,
                         switched_in=switched_in)
    out["_events"] = events
    return out


class DexAwareVenue(FakeVenue):
    """Like HlVenue: our own read only covers the hip3 dex when asked
    (`also_dexes`), and reports which dexes it read."""

    def __init__(self) -> None:
        super().__init__()
        self.also_seen: List[Optional[List[str]]] = []

    def account_state(self, user: str, also_dexes: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        acct = super().account_state(user)
        if acct is None or user != OUR:
            return acct
        self.also_seen.append(also_dexes)
        read = [""] + list(also_dexes or [])
        out = dict(acct)
        out["positions"] = {c: p for c, p in acct["positions"].items()
                            if (c.split(":", 1)[0] if ":" in c else "") in read}
        out["dexes_read"] = read
        return out


def test_b1_hip3_copy_is_read_every_cycle_and_never_vanishes(engine_state):
    v = DexAwareVenue()
    v.set_account(OUR, 1000.0, available={"": 1000.0, "xyz": 1000.0})
    v.hold(LEADER1, "xyz:TSLA", 1.0, entry_px=100.0)
    out = run(v, cfg(), engine_state, now_ms=0)
    assert out["opened"] == ["xyz:TSLA"]
    v.hold(OUR, "xyz:TSLA", 0.2, entry_px=100.0, equity_perp_usd=1000.0)
    for t in (1, 2, 3):
        out = run(v, cfg(), engine_state, now_ms=t)
        assert out["vanished"] == []
        assert v.also_seen[-1] == ["xyz"]                # the copy's dex is always read
    assert [c.coin for c in engine_state.all_copies()] == ["xyz:TSLA"]


def test_b1_a_dex_the_read_did_not_cover_is_unknown_not_gone(engine_state):
    """Even if a venue ignores also_dexes, a copy on an unread dex is kept."""

    class BlindVenue(DexAwareVenue):
        def account_state(self, user, also_dexes=None):
            return super().account_state(user, None)       # never covers xyz

    v = BlindVenue()
    v.set_account(OUR, 1000.0)
    engine_state.put_copy(Copy("xyz:TSLA", LEADER1, 0, 5, False, "fixed_notional"))
    for t in (1, 2, 3):
        out = run(v, cfg(), engine_state, now_ms=t)
        assert out["vanished"] == []
    assert [c.coin for c in engine_state.all_copies()] == ["xyz:TSLA"]


def test_b1_a_filled_pending_open_missing_from_the_read_is_kept(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    engine_state.put_copy(Copy("BTC", LEADER1, 0, 5, False, "fixed_notional", pending_cloid="0x" + "a" * 32))
    v.statuses["0x" + "a" * 32] = "filled"
    run(v, cfg(), engine_state, now_ms=10 * 60_000)
    rows = engine_state.all_copies()
    assert [c.coin for c in rows] == ["BTC"] and rows[0].pending_cloid   # not deleted


class RecordingCredsVenue(FakeVenue):
    def __init__(self) -> None:
        super().__init__()
        self.creds_seen: List[Any] = []

    def set_leverage(self, coin, leverage, is_cross, creds=None):
        self.creds_seen.append(("lev", creds))
        return super().set_leverage(coin, leverage, is_cross)

    def market(self, coin, is_buy, size, mid, reduce_only=False, cloid=None, max_slippage_pct=1.0,
               creds=None):
        self.creds_seen.append(("market", creds))
        return super().market(coin, is_buy, size, mid, reduce_only, cloid, max_slippage_pct)

    def close(self, coin, cloid=None, creds=None):
        self.creds_seen.append(("close", creds))
        return super().close(coin, cloid)


def test_b2_every_write_of_a_cycle_carries_the_pinned_credentials(engine_state):
    pinned = object()
    v = RecordingCredsVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    run(v, cfg(), engine_state, now_ms=0, creds=pinned)
    v.hold(OUR, "BTC", 0.2, entry_px=100.0, equity_perp_usd=1000.0)
    v.hold(LEADER1, "BTC", 0.0)
    run(v, cfg(), engine_state, now_ms=1, creds=pinned)
    kinds = [k for k, _ in v.creds_seen]
    assert "lev" in kinds and "market" in kinds and "close" in kinds
    assert all(c is pinned for _, c in v.creds_seen)


def test_b2_venue_refuses_a_pinned_write_after_the_active_account_changed(monkeypatch):
    from hl import env, venue as hv
    creds = env.Credentials("0x" + "1" * 40, "0x" + "2" * 64)
    monkeypatch.setattr(env, "account_address", lambda: "0x" + "3" * 40)   # switched mid-cycle
    out = hv.HlVenue().market("BTC", True, 1.0, 100.0, creds=creds)
    assert out["ok"] is False and "active account changed" in out["error"]


# ── M3: an unreliable day PnL must not silently switch the loss limit off ──

def test_m3_loss_limit_pauses_opens_after_an_hour_of_unreliable_day_pnl(engine_state):
    from engine.core import UNRELIABLE_GRACE_MS, _halt_check
    s = cfg(daily_loss_limit_usd=-10.0)
    log: List[Any] = []
    assert _halt_check(engine_state, s, None, log.append, 0, reliable=False) is None
    assert _halt_check(engine_state, s, None, log.append, UNRELIABLE_GRACE_MS - 1, reliable=False) is None
    reason = _halt_check(engine_state, s, None, log.append, UNRELIABLE_GRACE_MS, reliable=False)
    assert reason and "degraded" in reason
    assert [e.action for e in log] == ["halt"]                  # logged once
    _halt_check(engine_state, s, None, log.append, UNRELIABLE_GRACE_MS + 5, reliable=False)
    assert len(log) == 1
    assert _halt_check(engine_state, s, 0.0, log.append, UNRELIABLE_GRACE_MS + 9, reliable=True) is None


def test_m3_limit_off_never_pauses(engine_state):
    from engine.core import UNRELIABLE_GRACE_MS, _halt_check
    s = cfg(daily_loss_limit_usd=0.0)
    assert _halt_check(engine_state, s, None, lambda e: None, 10 * UNRELIABLE_GRACE_MS, reliable=False) is None


# ── H7: switching to another account must not copy every trader's whole book ──

def test_h7_traders_configured_before_the_account_started_are_baselined(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    # First cycle after switching INTO this account, LEADER1 already configured.
    out = run(v, cfg(), engine_state, now_ms=1_000, switched_in=True)
    assert out["opened"] == []
    assert any(e.action == "baseline" for e in out["_events"])


def test_h7_a_trader_invested_after_the_account_started_copies_his_book(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    run(v, cfg(leaders=[]), engine_state, now_ms=1_000, switched_in=True)   # switched in, no traders yet
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    s = cfg(leader_overrides={LEADER1: {"invested_ms": 2_000}})
    out = run(v, s, engine_state, now_ms=3_000)
    assert out["opened"] == ["BTC"]


def test_h7_a_fresh_install_without_a_switch_still_copies_the_book(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    out = run(v, cfg(), engine_state, now_ms=1_000)               # no switch
    assert out["opened"] == ["BTC"]
