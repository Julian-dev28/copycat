"""Pure allocation sizing (contract v4/v5): engine.sizing allocation_notional,
plan_allocation (concentrate / bump / skip), liquidity split, pacing.
Every expected number is computed by hand in the comment next to it."""
from __future__ import annotations

import pytest
from engine import pacing, sizing

from contracts.models import ExposureMode, Settings, SmallAccountMode


def alloc(**kw) -> Settings:
    base = dict(sizing_mode="allocation", allocation_usd=1000.0, exposure_mode="match",
                target_leverage=5)
    base.update(kw)
    return Settings(**base)


# ── allocation_notional ─────────────────────────────────────────────────────

def test_match_is_his_notional_over_his_equity_times_the_allocation():
    # $10k added on $1M equity, $1,000 invested: 10_000 / 1_000_000 * 1000 = $10
    assert sizing.allocation_notional(alloc(), 10_000, 1_000_000, 0.0) == pytest.approx(10.0)


def test_target_is_his_share_of_gross_times_allocation_times_leverage():
    # $75k of a $100k book, $1,000 at 5x: 0.75 * 1000 * 5 = $3,750
    s = alloc(exposure_mode="target", target_leverage=5)
    assert sizing.allocation_notional(s, 75_000, 1_000_000, 100_000) == pytest.approx(3750.0)
    # capped leverage 3 (coin max): 0.75 * 1000 * 3 = $2,250, margin still $750
    assert sizing.allocation_notional(s, 75_000, 1_000_000, 100_000, lev=3) == pytest.approx(2250.0)


def test_zero_denominators_size_zero():
    assert sizing.allocation_notional(alloc(), 10_000, 0.0, 0.0) == 0.0
    assert sizing.allocation_notional(alloc(exposure_mode="target"), 10_000, 1e6, 0.0) == 0.0
    assert sizing.allocation_notional(alloc(allocation_usd=0.0), 10_000, 1e6, 1e5) == 0.0


def test_open_and_add_route_allocation_through_the_same_formula():
    s = alloc(exposure_mode="target")
    assert sizing.open_notional(s, 25_000, 1e6, 50.0, 1, 5, 100_000) == pytest.approx(1250.0)
    assert sizing.add_notional(s, 25_000, 1e6, 50.0, 1, 999.0, 9.0, 100_000, 5) == pytest.approx(1250.0)


def test_target_mode_exchange_leverage_ignores_leverage_mode_and_is_capped():
    s = alloc(exposure_mode="target", target_leverage=5, leverage_mode="max")
    assert sizing.exchange_leverage(s, 20.0, 50) == 5
    assert sizing.exchange_leverage(s, 20.0, 3) == 3                      # coin max
    assert sizing.exchange_leverage(s.model_copy(update={"max_position_leverage": 2}), 20.0, 50) == 2
    # match mode keeps the leverage_mode logic (max -> the coin max)
    assert sizing.exchange_leverage(alloc(exposure_mode="match"), 2.0, 40) == 40


def test_allocation_room_is_the_remaining_margin_times_leverage():
    # cap 1000 * 1.02 = 1020; 1000 used -> $20 margin left, at 5x = $100 notional
    assert sizing.allocation_room_ntl(alloc(), 1000.0, 5) == pytest.approx(100.0)
    assert sizing.allocation_room_ntl(alloc(), 1100.0, 5) == 0.0


def test_bump_allowed_by_small_account_mode():
    assert sizing.bump_allowed(alloc(small_account_mode="bump"))
    assert not sizing.bump_allowed(alloc(small_account_mode="concentrate"))
    assert not sizing.bump_allowed(Settings(small_account_mode="skip", min_order_bump=True))
    assert sizing.bump_allowed(Settings(small_account_mode="concentrate", min_order_bump=True))
    assert not sizing.bump_allowed(Settings(min_order_bump=False))


# ── the $20 wallet copying a 15-position whale ──────────────────────────────

# $1,000k gross book; target 5x on $20 -> $100 of notional to spread
WHALE_K = [300, 200, 100, 100, 50, 50, 50, 30, 30, 30, 20, 20, 10, 5, 5]


def whale() -> dict:
    return {f"C{i + 1:02d}": {"szi": k * 1000 / 100.0, "entry_px": 100.0, "lev": 10.0}
            for i, k in enumerate(WHALE_K)}


def plan(mode: SmallAccountMode, **kw):
    pos = whale()
    return sizing.plan_allocation(pos, 1_000_000.0, 20.0, ExposureMode.target, 5, mode,
                                  {c: 50 for c in pos}, **kw)


def test_concentrate_picks_his_top_four_and_spreads_the_whole_allocation():
    p = plan(SmallAccountMode.concentrate)
    # top 4 = 700k: 300/700*100 = 42.857, 200/700*100 = 28.571, 100/700*100 = 14.286 (x2).
    # Adding the next (50k) would make it 50/750*100 = 6.67 < 10.5, so it is dropped.
    assert p["copied"] == ["C01", "C02", "C03", "C04"]
    by = {r["coin"]: r for r in p["slices"]}
    assert by["C01"]["notional_usd"] == pytest.approx(300 / 700 * 100)
    assert by["C02"]["notional_usd"] == pytest.approx(200 / 700 * 100)
    assert by["C04"]["notional_usd"] == pytest.approx(100 / 700 * 100)
    assert p["planned_notional_usd"] == pytest.approx(100.0)
    assert p["planned_margin_usd"] == pytest.approx(20.0)                 # the whole $20
    assert p["scale"] == pytest.approx(1000 / 700)
    assert len(p["skipped"]) == 11 and "concentrate" in by["C05"]["reason"]
    # every position clears $10.50 at 10.5 / (5k/1M * 5) = $420
    assert p["min_allocation_for_full_book"] == pytest.approx(420.0)


def test_concentrate_never_drops_a_coin_we_already_hold():
    p = plan(SmallAccountMode.concentrate, held=["C15"])
    by = {r["coin"]: r for r in p["slices"]}
    # C15 stays in the eligible set (scale = 1000 / (700 + 5)), it is not dropped by
    # concentrate; an add to it is still subject to the $10.50 minimum.
    assert p["scale"] == pytest.approx(1000 / 705)
    assert "concentrate" not in (by["C15"]["reason"] or "")
    assert "minimum" in by["C15"]["reason"]


def test_bump_rounds_up_in_coin_order_until_the_cap_is_hit():
    p = plan(SmallAccountMode.bump)
    by = {r["coin"]: r for r in p["slices"]}
    # C01 $30 (margin 6), C02 $20 (4), C03..C06 bumped to 10.50 (2.10 each): 18.40 used.
    # C07 would make 20.50 > cap 20.40 -> skipped; C14/C15 ($0.50) are under 25% of the floor.
    assert p["copied"] == ["C01", "C02", "C03", "C04", "C05", "C06"]
    assert [by[c]["status"] for c in ("C03", "C05")] == ["bump", "bump"]
    assert p["planned_margin_usd"] == pytest.approx(18.4)
    assert by["C07"]["status"] == "skip"


def test_skip_keeps_only_slices_over_the_minimum():
    p = plan(SmallAccountMode.skip)
    assert p["copied"] == ["C01", "C02"]                                   # $30 and $20
    assert p["planned_notional_usd"] == pytest.approx(50.0)


def test_match_plan_and_min_allocation():
    pos = {"BTC": {"szi": 1000.0, "entry_px": 100.0}, "ETH": {"szi": -100.0, "entry_px": 100.0}}
    p = sizing.plan_allocation(pos, 1_000_000.0, 1000.0, ExposureMode.match, 5,
                               SmallAccountMode.skip, {"BTC": 50, "ETH": 50})
    by = {r["coin"]: r for r in p["slices"]}
    assert by["BTC"]["notional_usd"] == pytest.approx(100.0)               # 100k/1M * 1000
    assert by["ETH"]["status"] == "skip" and by["ETH"]["side"] == "short"  # $10 < 10.50
    assert p["min_allocation_for_full_book"] == pytest.approx(1050.0)      # 10.5 * 1M / 10k


def test_plan_reports_fills_over_n_cycles():
    pos = {"xyz:THIN": {"szi": 50_000.0, "entry_px": 100.0}}               # $5M
    p = sizing.plan_allocation(pos, 10_000_000.0, 500_000.0, ExposureMode.match, 5,
                               SmallAccountMode.concentrate, {"xyz:THIN": 50},
                               liq_cap={"xyz:THIN": 80_000.0})
    # 5M/10M * 500k = $250k; at $80k a cycle: ceil(3.125) = 4 cycles
    assert p["slices"][0]["fill_cycles"] == 4 and p["multi_cycle"]


# ── liquidity ───────────────────────────────────────────────────────────────

def test_liquidity_cap_is_the_smaller_of_volume_share_and_depth():
    assert sizing.liquidity_cap(20_000_000, 80_000, 0.5) == pytest.approx(80_000)   # 0.5% = 100k
    assert sizing.liquidity_cap(10_000_000, 80_000, 0.5) == pytest.approx(50_000)
    assert sizing.liquidity_cap(None, 80_000, 0.5) is None


def test_split_order():
    assert sizing.split_order(250_000, 80_000) == (80_000, 170_000, None)
    assert sizing.split_order(85.0, 80.0) == (80.0, 0.0, None)              # carry $5 < min: dropped
    assert sizing.split_order(40_000, None) == (40_000, 0.0, None)          # reads failed, < $50k
    send, carry, why = sizing.split_order(60_000, None)
    assert (send, carry) == (0.0, 0.0) and "uncapped limit" in why
    assert "under the" in sizing.split_order(100.0, 5.0)[2]


# ── pacing ──────────────────────────────────────────────────────────────────

def test_25_leaders_stretch_the_poll_interval():
    leaders = {f"L{i}": ["BTC"] for i in range(25)}
    # 26 accounts x (clearinghouse 2 + spot 2) = 104, + allMids main 2 + our ledger 20 = 126
    w = pacing.cycle_weight(["BTC"], leaders)
    assert w == 126
    # 126 * 60 / (1200 * 0.6) = 10.5 s
    assert pacing.effective_poll_s(5.0, w) == pytest.approx(126 * 60 / 720)
    assert pacing.effective_poll_s(30.0, w) == 30.0                         # never below the setting


def test_hip3_dexes_add_a_clearinghouse_read_each():
    assert pacing.account_weight(["BTC", "xyz:TSLA", "flx:OIL"]) == 2 * 3 + 2


def test_fill_fee_uses_the_reported_fee_else_the_taker_estimate():
    from engine.core import TAKER_FEE_BPS, fill_fee_usd
    assert fill_fee_usd({"fee": "-0.12"}, 1000.0) == 0.12
    assert fill_fee_usd({}, 1000.0) == 1000.0 * TAKER_FEE_BPS / 10_000   # $0.45 at 4.5 bps
    assert fill_fee_usd({}, 0.0) == 0.0


# ── v7: plan_copy (global wallets on the Settings tab) ──────────────────────

def test_plan_copy_fixed_margin_at_max_leverage():
    pos = {"BTC": {"szi": 10.0, "entry_px": 100.0}, "ETH": {"szi": -5.0, "entry_px": 100.0}}
    s = Settings(sizing_mode="fixed_margin", fixed_margin_usd=1.0, leverage_mode="max")
    p = sizing.plan_copy(s, pos, 1e6, {"BTC": 40, "ETH": 25})
    by = {r["coin"]: r for r in p["slices"]}
    # $1 margin x coin max: BTC $40, ETH $25, margin $1 each
    assert (by["BTC"]["notional_usd"], by["BTC"]["leverage"]) == (40.0, 40)
    assert (by["ETH"]["notional_usd"], by["ETH"]["side"]) == (25.0, "short")
    assert p["planned_margin_usd"] == pytest.approx(2.0) and p["min_allocation_for_full_book"] is None


def test_plan_copy_bump_floor_max_open_copies_and_taken():
    pos = {c: {"szi": 1.0, "entry_px": 100.0} for c in ("AAA", "BBB", "CCC", "DDD")}
    s = Settings(sizing_mode="fixed_margin", fixed_margin_usd=0.1, leverage_mode="fixed",
                 leverage=50, max_open_copies=3)
    p = sizing.plan_copy(s, pos, 1e6, {c: 50 for c in pos}, open_copies=1, taken={"AAA": "0xother"})
    by = {r["coin"]: r for r in p["slices"]}
    # 0.1 x 50 = $5 >= 25% of 10.50 -> bumped; AAA owned elsewhere; 1 open + 2 = cap 3 -> DDD skipped
    assert "owned by wallet" in by["AAA"]["reason"]
    assert (by["BBB"]["status"], by["BBB"]["notional_usd"]) == ("bump", 10.5)
    assert by["CCC"]["status"] == "bump" and "max_open_copies" in by["DDD"]["reason"]
    tiny = sizing.plan_copy(s.model_copy(update={"fixed_margin_usd": 0.01}), pos, 1e6,
                            {c: 50 for c in pos})
    assert tiny["copied"] == []                                     # $0.50 < 25% of the floor


def test_plan_copy_proportional_needs_our_equity():
    pos = {"BTC": {"szi": 1000.0, "entry_px": 100.0}}
    s = Settings(sizing_mode="proportional", sleeve_frac=0.5, size_multiplier=1.0)
    # 100k / 1M * (10_000 * 0.5 / 2 leaders) = $250
    p = sizing.plan_copy(s, pos, 1e6, {"BTC": 50}, our_equity=10_000.0, n_leaders=2)
    assert p["slices"][0]["notional_usd"] == pytest.approx(250.0)
    q = sizing.plan_copy(s, pos, 1e6, {"BTC": 50})
    assert "equity unknown" in q["slices"][0]["reason"]
