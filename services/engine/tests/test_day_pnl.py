"""Day PnL net of transfers (UX audit #2: a deposit was read as +$24 PnL, and a
withdrawal would have tripped the daily loss halt). engine.daypnl is pure;
core._update_day_pnl/_halt_check wire it to the venue ledger and state."""
from __future__ import annotations

import pytest

from engine import core, daypnl

from engine_fakes import LEADER1, OUR
from test_core import cfg, run

H = 3_600_000
DAY = 24 * H
T0 = 10 * DAY            # 00:00 UTC of some day
LIMIT = dict(leaders=[LEADER1], daily_loss_limit_usd=-100.0, enabled=False)
OTHER = "0x" + "9" * 40


def dep(t, usd, kind="deposit", **kw):
    return {"time": t, "hash": f"0x{t:x}{kind}", "delta": {"type": kind, "usdc": str(usd), **kw}}


# ── the regressions ─────────────────────────────────────────────────────────

def test_a_mid_day_deposit_does_not_change_day_pnl(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    assert out["day_pnl_usd"] == 0.0 and out["day_pnl_reliable"] is True

    venue.set_account(OUR, 1500.0)                         # +500 deposit, no trading
    venue.ledger[OUR] = [dep(T0 + 2 * H, 500)]
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 3 * H)
    assert out["day_pnl_usd"] == pytest.approx(0.0)
    assert out["day_pnl_reliable"] is True
    assert venue.ledger_calls[-1] == (OUR, T0)             # read from the anchor's time


def test_a_mid_day_withdrawal_does_not_trigger_the_loss_halt(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)

    venue.set_account(OUR, 499.0)                          # withdrew 500 (+$1 fee)
    venue.ledger[OUR] = [dep(T0 + H, 500, "withdraw", fee="1.0")]
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 2 * H)
    assert out["day_pnl_usd"] == pytest.approx(0.0)
    assert out["halted_reason"] is None
    assert not [e for e in out["_events"] if e.action == "halt"]


def test_real_losses_still_halt_after_a_deposit(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    venue.set_account(OUR, 1350.0)                         # deposited 500, lost 150
    venue.ledger[OUR] = [dep(T0 + H, 500)]
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 2 * H)
    assert out["day_pnl_usd"] == pytest.approx(-150.0)
    assert out["halted_reason"] and "day PnL $-150.00" in out["halted_reason"]


# ── unreliable: hold the last good value, never halt or resume on it ────────

def test_a_failed_ledger_read_holds_the_last_good_value_and_never_halts(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    venue.set_account(OUR, 990.0)
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + H)
    assert out["day_pnl_usd"] == pytest.approx(-10.0)

    venue.set_account(OUR, 500.0)                          # a withdrawal we cannot see
    venue.ledger[OUR] = None
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 2 * H)
    assert out["day_pnl_reliable"] is False
    assert out["day_pnl_usd"] == pytest.approx(-10.0)      # last good, not -500
    assert out["halted_reason"] is None
    errs = [e for e in out["_events"] if e.action == "error"]
    assert len(errs) == 1 and "day PnL unreliable: ledger read failed" in errs[0].reason

    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 2 * H + 5000)
    assert not [e for e in out["_events"] if e.action == "error"]   # one event per stretch


def test_unreliable_never_resumes_a_halt(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    venue.set_account(OUR, 800.0)
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + H)
    assert out["halted_reason"]                            # real -200

    venue.set_account(OUR, 5000.0)                         # a deposit we cannot net out
    venue.ledger[OUR] = None
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 2 * H)
    assert out["day_pnl_reliable"] is False
    assert out["halted_reason"] and "holding" in out["halted_reason"]
    assert not [e for e in out["_events"] if e.action == "resume"]

    venue.ledger[OUR] = [dep(T0 + H + 1, 4200)]            # read works again: still -200
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + 3 * H)
    assert out["day_pnl_reliable"] is True
    assert out["day_pnl_usd"] == pytest.approx(-200.0)
    assert out["halted_reason"] and "holding" not in out["halted_reason"]


def test_turning_the_limit_off_resumes_even_when_unreliable(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    venue.set_account(OUR, 800.0)
    assert run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + H)["halted_reason"]
    venue.ledger[OUR] = None
    out = run(venue, cfg(**{**LIMIT, "daily_loss_limit_usd": 0.0}), engine_state, now_ms=T0 + 2 * H)
    assert out["halted_reason"] is None


def test_a_transfer_settling_inside_the_read_window_is_unreliable(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)
    now = T0 + 2 * H
    venue.set_account(OUR, 1000.0)                         # deposit not in this equity read yet
    venue.ledger[OUR] = [dep(now - 2000, 500)]
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=now)
    assert out["day_pnl_reliable"] is False and out["halted_reason"] is None
    venue.set_account(OUR, 1500.0)
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=now + daypnl.AMBIGUITY_MS + 1)
    assert out["day_pnl_reliable"] is True and out["day_pnl_usd"] == pytest.approx(0.0)


def test_a_new_utc_day_reanchors_without_a_ledger_read(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.ledger[OUR] = None                               # would fail if read
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + DAY)
    assert out["day_pnl_usd"] == 0.0 and out["day_pnl_reliable"] is True
    assert venue.ledger_calls == []


def test_a_legacy_anchor_without_ts_reads_from_the_utc_day_start(engine_state, venue):
    engine_state.set_kv("day_anchor", {"day": "1970-01-11", "equity_usd": 1000.0})
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + H)
    assert venue.ledger_calls == [(OUR, T0)]


def test_a_venue_that_raises_is_unreliable_not_a_crash(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    run(venue, cfg(**LIMIT), engine_state, now_ms=T0)

    def boom(user, start_ms):
        raise RuntimeError("x")
    venue.ledger_updates = boom
    out = run(venue, cfg(**LIMIT), engine_state, now_ms=T0 + H)
    assert out["day_pnl_reliable"] is False and out["day_pnl_usd"] == 0.0


def test_status_carries_day_pnl_reliable():
    from contracts.models import EngineStatus
    assert EngineStatus(running=True, enabled=True, dry_run=False).day_pnl_reliable is True


# ── daypnl.delta_usd: every ledger shape curled 2026-10-11 ──────────────────

US = OUR.lower()


@pytest.mark.parametrize("delta,usd", [
    ({"type": "deposit", "usdc": "1964.72"}, 1964.72),
    ({"type": "withdraw", "usdc": "9999.0", "nonce": 1, "fee": "1.0"}, -10000.0),
    ({"type": "accountClassTransfer", "usdc": "47000.0", "toPerp": False}, 0.0),
    ({"type": "accountClassTransfer", "usdc": "1476.68", "toPerp": True}, 0.0),
    ({"type": "internalTransfer", "usdc": "1.0", "user": OTHER, "destination": US, "fee": "0.3"}, 1.0),
    ({"type": "internalTransfer", "usdc": "1.0", "user": US, "destination": OTHER, "fee": "0.3"}, -1.3),
    ({"type": "subAccountTransfer", "usdc": "50.0", "user": OTHER, "destination": US}, 50.0),
    ({"type": "subAccountTransfer", "usdc": "50.0", "user": US, "destination": OTHER}, -50.0),
    ({"type": "send", "user": OTHER, "destination": US, "sourceDex": "spot", "destinationDex": "",
      "token": "USDC", "amount": "100.0", "usdcValue": "100.0", "fee": "0.0", "feeToken": ""}, 100.0),
    ({"type": "send", "user": US, "destination": OTHER, "sourceDex": "", "destinationDex": "",
      "token": "USDC", "amount": "100.0", "usdcValue": "100.0", "fee": "1.0", "feeToken": ""}, -101.0),
    ({"type": "send", "user": US, "destination": US, "sourceDex": "", "destinationDex": "xyz",
      "token": "USDC", "amount": "40.0", "fee": "0.0", "feeToken": ""}, 0.0),
    ({"type": "send", "user": OTHER, "destination": US, "token": "HYPE", "amount": "3.0",
      "usdcValue": "120.0", "fee": "0.0", "feeToken": ""}, 0.0),
    ({"type": "spotTransfer", "token": "USDC", "amount": "1.0", "usdcValue": "1.0",
      "user": OTHER, "destination": US, "fee": "0.0", "feeToken": ""}, 1.0),
    ({"type": "spotTransfer", "token": "NFT", "amount": "3000.0", "usdcValue": "300.03",
      "user": US, "destination": OTHER, "fee": "1.0", "feeToken": ""}, -1.0),
    ({"type": "vaultDeposit", "vault": OTHER, "usdc": "5000.0"}, -5000.0),
    ({"type": "vaultWithdraw", "vault": OTHER, "user": US, "requestedUsd": "50000.0",
      "netWithdrawnUsd": "49990.0"}, 49990.0),
    ({"type": "vaultCreate", "vault": OTHER, "usdc": "100.0", "fee": "100.0"}, -200.0),
    ({"type": "liquidation", "liquidatedNtlPos": "1.0", "accountValue": "1.0"}, 0.0),
    ({"type": "spotGenesis", "token": "X", "amount": "1.0"}, 0.0),
    ({"type": "cStakingTransfer", "token": "HYPE", "amount": "1.0", "isDeposit": True}, 0.0),
])
def test_every_known_ledger_shape(delta, usd):
    assert daypnl.delta_usd(delta, US) == pytest.approx(usd)


def test_an_unknown_ledger_type_is_a_problem_not_a_guess():
    net, problem = daypnl.net_transfers(
        [{"time": 5, "delta": {"type": "somethingNew", "usdc": "9"}}], US, 0, 10 ** 9)
    assert problem == "unknown ledger type 'somethingNew'"


def test_rows_before_the_anchor_are_already_in_its_equity():
    net, problem = daypnl.net_transfers([dep(5, 100), dep(20, 7)], US, 10, 10 ** 9)
    assert (net, problem) == (7.0, None)


def test_a_garbage_amount_is_a_problem():
    _net, problem = daypnl.net_transfers([dep(20, "abc")], US, 0, 10 ** 9)
    assert problem == "unreadable ledger row"


def test_core_exposes_no_unadjusted_path():
    # the old signature (state, now_ms, equity) is gone: every caller nets transfers
    import inspect
    assert "venue" in inspect.signature(core._update_day_pnl).parameters
