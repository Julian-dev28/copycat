"""Regression tests for docs/audit/AUDIT_2026-10.md medium findings."""
from __future__ import annotations

from typing import Any, List

from engine import core
from engine_fakes import LEADER1, OUR, FakeVenue

from contracts.models import Settings


def cfg(**kw) -> Settings:
    base = dict(enabled=True, dry_run=False, leaders=[LEADER1], sizing_mode="fixed_notional",
                fixed_notional_usd=20.0, max_worse_entry_pct=100.0)
    base.update(kw)
    return Settings(**base)


def run(venue, settings, state, now_ms=0):
    events: List[Any] = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append)
    out["_events"] = events
    return out


# ── M2: a transient rejection is retried, not ignored until he goes flat ──

def test_m2_rate_limited_open_is_retried_and_copied_once_it_clears(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    v.reject_error["BTC"] = "(429, None, 'too many requests', ...)"
    out = run(v, cfg(), engine_state, now_ms=0)
    assert out["opened"] == [] and "retrying" in out["skipped"]["BTC"]
    assert engine_state.get_copy("BTC") is None                 # no stale pending row
    del v.reject_error["BTC"]
    out = run(v, cfg(), engine_state, now_ms=5_000)
    assert out["opened"] == ["BTC"]
    assert (engine_state.get_kv("transient_rejects") or {}) == {}


def test_m2_slippage_cap_retries(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "ETH", 1.0, entry_px=100.0)
    v.reject_error["ETH"] = "slippage cap"
    run(v, cfg(), engine_state, now_ms=0)
    del v.reject_error["ETH"]
    assert run(v, cfg(), engine_state, now_ms=5_000)["opened"] == ["ETH"]


def test_m2_permanent_rejection_still_ignores(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    v.reject_error["BTC"] = "Order has invalid size."
    run(v, cfg(), engine_state, now_ms=0)
    del v.reject_error["BTC"]
    assert run(v, cfg(), engine_state, now_ms=5_000)["opened"] == []   # ignored until flat


def test_m2_retries_are_bounded(engine_state):
    v = FakeVenue()
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    v.reject_error["BTC"] = "Insufficient margin to place order."
    for i in range(core._TRANSIENT_MAX_TRIES + 1):
        out = run(v, cfg(), engine_state, now_ms=i * 1_000)
    assert "retrying" not in out["skipped"]["BTC"]
    n = len(v.cloids)
    del v.reject_error["BTC"]
    run(v, cfg(), engine_state, now_ms=60_000)
    assert len(v.cloids) == n                                    # gave up: ignored until flat


def test_m2_classifier():
    for e in ("(429, None, 'null', None, None)", "Too many requests", "slippage cap",
              "Insufficient margin to place order. asset=0", "Order could not immediately match against any resting orders."):
        assert core.is_transient_reject(e), e
    for e in ("Order has invalid size.", "rejected", None, "Post only order would have immediately matched"):
        assert not core.is_transient_reject(e), e


# ── M4: a stop re-posted mid-cycle is not deleted with the old one ──

def test_m4_clear_stop_keeps_a_flag_rewritten_during_the_cycle(tmp_path, monkeypatch):
    from engine import public
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    d = tmp_path / "stop"
    d.mkdir()
    f = d / f"{LEADER1}.flag"
    f.write_text('{"close_positions": false, "requested_ms": 1}')
    seen = public.read_stop_flags()[LEADER1]
    assert seen[0] is False
    f.write_text('{"close_positions": true, "requested_ms": 2}')        # user re-posts mid-cycle
    assert public._clear_stop(LEADER1, seen[1]) is False and f.exists()
    assert public.read_stops() == {LEADER1: True}
    assert public._clear_stop(LEADER1, f.read_text()) is True and not f.exists()
    assert public._clear_stop(LEADER1, "x") is False                     # already gone: no error


# ── S7: realized PnL of unconfirmed exits comes from our real HL fills ──

def _open_btc(v, state):
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    assert run(v, cfg(), state, now_ms=0)["opened"] == ["BTC"]
    v.hold(OUR, "BTC", 0.2, entry_px=100.0, equity_perp_usd=1000.0)


def _realized(state):
    return round(state.get_ledger(LEADER1)["realized_pnl_usd"], 6)


def test_s7_ambiguous_close_that_filled_books_hl_closed_pnl(engine_state):
    v = FakeVenue()
    _open_btc(v, engine_state)
    v.user_fills[OUR] = []
    before = _realized(engine_state)
    v.hold(LEADER1, "BTC", 0.0)
    v.close_ambiguous.add("BTC")
    run(v, cfg(), engine_state, now_ms=10_000)                 # close sent, outcome unknown
    cloid = v.close_cloids[-1]
    v.close_ambiguous.discard("BTC")
    v.hold(OUR, "BTC", 0.0)                                    # it did fill
    v.user_fills[OUR] = [{"coin": "BTC", "time": 10_001, "cloid": cloid, "closedPnl": "5.0", "fee": "0.1"},
                         {"coin": "BTC", "time": 10_001, "cloid": "0x" + "9" * 32, "closedPnl": "99", "fee": "0"},
                         {"coin": "ETH", "time": 10_001, "closedPnl": "77", "fee": "0"}]
    for t in (20_000, 30_000):
        run(v, cfg(), engine_state, now_ms=t)
    assert engine_state.get_copy("BTC") is None
    assert _realized(engine_state) == round(before + 4.9, 6)   # only the parked close's fill


def test_s7_liquidated_copy_books_the_liquidation_fill(engine_state):
    v = FakeVenue()
    _open_btc(v, engine_state)
    before = _realized(engine_state)
    v.hold(OUR, "BTC", 0.0)                                    # liquidated, leader still in
    v.user_fills[OUR] = [{"coin": "BTC", "time": 15_000, "closedPnl": "-30", "fee": "0.5"}]
    for t in (20_000, 30_000):
        out = run(v, cfg(), engine_state, now_ms=t)
    assert out["vanished"] == ["BTC"]
    assert _realized(engine_state) == round(before - 30.5, 6)


def test_s7_fills_read_failure_books_nothing_and_does_not_crash(engine_state):
    v = FakeVenue()
    _open_btc(v, engine_state)
    before = _realized(engine_state)
    v.hold(OUR, "BTC", 0.0)                                    # no user_fills: read fails
    for t in (20_000, 30_000):
        run(v, cfg(), engine_state, now_ms=t)
    assert _realized(engine_state) == before


# ── M9: a pending reduce never settles on a read that skipped its dex ──

def test_m9_pending_reduce_waits_for_a_read_that_covers_its_dex(engine_state):
    from test_audit_blockers import DexAwareVenue

    class BlindVenue(DexAwareVenue):
        def account_state(self, user, also_dexes=None):
            return super().account_state(user, None)

    v = BlindVenue()
    v.set_account(OUR, 1000.0)
    cloid = "0x" + "c" * 32
    engine_state.set_kv("pending_reduces", {"xyz:TSLA": {
        "cloid": cloid, "leader": LEADER1, "prev": 1.0, "cur": 0.5, "size_before": 0.2,
        "order_size": 0.1, "sent_ms": 0, "szi": 0.2, "entry_px": 100.0}})
    v.statuses[cloid] = "filled"
    run(v, cfg(leaders=[]), engine_state, now_ms=60_000)
    assert "xyz:TSLA" in engine_state.get_kv("pending_reduces")


# ── S9: positions show HL's actual leverage ──

def test_s9_position_leverage_is_hls_not_the_requested_one(engine_state):
    v = FakeVenue()
    _open_btc(v, engine_state)
    v.accounts[OUR]["raw_positions"]["BTC"]["leverage"] = {"type": "cross", "value": 7}
    out = run(v, cfg(), engine_state, now_ms=5_000)
    pos = [p for p in out["positions"] if p.coin == "BTC"][0]
    assert pos.leverage == 7 and pos.is_cross is True


def test_s9_falls_back_to_the_requested_leverage_without_a_reading():
    assert core._actual_leverage({}, 3) == 3
    assert core._actual_leverage({"leverage": {"value": "x"}}, 3) == 3
    assert core._actual_leverage({"leverage": {"value": 0.4}}, 3) == 1


# ── S10: fees use the account's real HL taker rate ──

def test_s10_fee_rate_is_read_hourly_and_used_for_fees(engine_state):
    v = FakeVenue()
    calls = []
    v.taker_fee_rate = lambda user: calls.append(user) or 0.0002          # 2 bps (tier + discounts)
    v.set_account(OUR, 1000.0)
    v.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    run(v, cfg(), engine_state, now_ms=0)
    assert calls == [OUR] and core.fee_bps(engine_state) == 2.0
    fee = engine_state.get_ledger(LEADER1)["fees_usd"]
    assert abs(fee - 20.0 * 2.0 / 10_000) < 1e-9                         # $20 open at 2 bps
    run(v, cfg(), engine_state, now_ms=30 * 60_000)
    assert calls == [OUR]                                                  # cached
    run(v, cfg(), engine_state, now_ms=61 * 60_000)
    assert len(calls) == 2


def test_s10_failed_or_absurd_reads_keep_the_default(engine_state):
    v = FakeVenue()
    v.taker_fee_rate = lambda user: 0.5
    v.set_account(OUR, 1000.0)
    run(v, cfg(), engine_state, now_ms=0)
    assert core.fee_bps(engine_state) == core.TAKER_FEE_BPS
