"""engine.sizing: pure functions, no venue, no state. <2s, no network."""
from __future__ import annotations

import pytest

from contracts.models import Settings
from engine import sizing


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


# ── open_notional ────────────────────────────────────────────────────────

def test_open_notional_proportional_formula():
    s = _settings(sizing_mode="proportional", sleeve_frac=0.5, size_multiplier=1.0)
    # his_added_ntl=100_000 his_equity=1_000_000 our_equity=1000 n_leaders=1
    # allocation = 1000*0.5/1 = 500; ntl = 100000/1e6*500 = 50
    ntl = sizing.open_notional(s, 100_000.0, 1_000_000.0, 1000.0, 1, 20)
    assert ntl == pytest.approx(50.0)


def test_open_notional_proportional_scales_with_size_multiplier():
    s = _settings(sizing_mode="proportional", sleeve_frac=0.5, size_multiplier=3.0)
    ntl = sizing.open_notional(s, 100_000.0, 1_000_000.0, 1000.0, 1, 20)
    assert ntl == pytest.approx(150.0)


def test_open_notional_proportional_zero_on_degraded_equity_or_leaders():
    s = _settings(sizing_mode="proportional")
    assert sizing.open_notional(s, 100.0, 0.0, 1000.0, 1, 20) == 0.0
    assert sizing.open_notional(s, 100.0, 1000.0, 1000.0, 0, 20) == 0.0


def test_open_notional_fixed_margin_is_margin_times_exchange_leverage():
    s = _settings(sizing_mode="fixed_margin", fixed_margin_usd=1.0)
    assert sizing.open_notional(s, 0.0, 0.0, 0.0, 1, 40) == pytest.approx(40.0)


def test_open_notional_fixed_notional_is_flat_regardless_of_leverage():
    s = _settings(sizing_mode="fixed_notional", fixed_notional_usd=25.0)
    assert sizing.open_notional(s, 0.0, 0.0, 0.0, 1, 1) == pytest.approx(25.0)
    assert sizing.open_notional(s, 0.0, 0.0, 0.0, 1, 40) == pytest.approx(25.0)


# ── add_notional ─────────────────────────────────────────────────────────

def test_add_notional_proportional_uses_same_formula_as_open():
    s = _settings(sizing_mode="proportional", sleeve_frac=0.5, size_multiplier=1.0)
    ntl = sizing.add_notional(s, 100_000.0, 1_000_000.0, 1000.0, 1, 999.0, 0.5)
    assert ntl == pytest.approx(50.0)  # his_added_ntl/his_equity/our_equity drive it, not the rest


def test_add_notional_fixed_margin_scales_current_notional_by_his_fraction():
    s = _settings(sizing_mode="fixed_margin", fixed_margin_usd=5.0)
    ntl = sizing.add_notional(s, 0.0, 0.0, 0.0, 1, our_current_notional=50.0, his_frac_added=0.5)
    assert ntl == pytest.approx(25.0)


def test_add_notional_fixed_notional_scales_current_notional_by_his_fraction():
    s = _settings(sizing_mode="fixed_notional", fixed_notional_usd=20.0)
    ntl = sizing.add_notional(s, 0.0, 0.0, 0.0, 1, our_current_notional=20.0, his_frac_added=1.0)
    assert ntl == pytest.approx(20.0)  # he doubled -> we double


# ── exchange_leverage ────────────────────────────────────────────────────

def test_exchange_leverage_max_mode_is_the_cap():
    s = _settings(leverage_mode="max", max_position_leverage=50)
    assert sizing.exchange_leverage(s, his_lev=3.0, coin_max=20) == 20
    assert sizing.exchange_leverage(s, his_lev=3.0, coin_max=80) == 50  # capped by max_position_leverage


def test_exchange_leverage_match_mode_ceils_and_caps():
    s = _settings(leverage_mode="match", max_position_leverage=50)
    assert sizing.exchange_leverage(s, his_lev=7.2, coin_max=20) == 8       # ceil(7.2)
    assert sizing.exchange_leverage(s, his_lev=30.0, coin_max=40) == 30
    s2 = _settings(leverage_mode="match", max_position_leverage=10)
    assert sizing.exchange_leverage(s2, his_lev=30.0, coin_max=40) == 10   # capped by max_position_leverage


def test_exchange_leverage_fixed_mode_uses_configured_value_and_caps():
    s = _settings(leverage_mode="fixed", leverage=15, max_position_leverage=50)
    assert sizing.exchange_leverage(s, his_lev=99.0, coin_max=40) == 15
    s2 = _settings(leverage_mode="fixed", leverage=45, max_position_leverage=20)
    assert sizing.exchange_leverage(s2, his_lev=99.0, coin_max=40) == 20   # capped by max_position_leverage
    s3 = _settings(leverage_mode="fixed", leverage=45, max_position_leverage=50)
    assert sizing.exchange_leverage(s3, his_lev=99.0, coin_max=10) == 10   # capped by coin_max


# ── worse_entry_ok ───────────────────────────────────────────────────────

def test_worse_entry_ok_long_blocked_above_pct_allowed_within():
    assert sizing.worse_entry_ok("long", mid=115.0, entry=100.0, pct=10.0) is False
    assert sizing.worse_entry_ok("long", mid=105.0, entry=100.0, pct=10.0) is True
    assert sizing.worse_entry_ok("long", mid=110.0, entry=100.0, pct=10.0) is True  # exactly at the edge


def test_worse_entry_ok_short_blocked_below_pct_allowed_within():
    assert sizing.worse_entry_ok("short", mid=85.0, entry=100.0, pct=10.0) is False
    assert sizing.worse_entry_ok("short", mid=95.0, entry=100.0, pct=10.0) is True
    assert sizing.worse_entry_ok("short", mid=90.0, entry=100.0, pct=10.0) is True


def test_worse_entry_ok_unknown_entry_always_allows():
    assert sizing.worse_entry_ok("long", mid=999.0, entry=0.0, pct=1.0) is True
    assert sizing.worse_entry_ok("short", mid=0.01, entry=-5.0, pct=1.0) is True


# ── bump ─────────────────────────────────────────────────────────────────

def test_bump_rounds_up_to_the_floor_when_close_enough_and_enabled():
    s = _settings(min_order_bump=True)
    assert sizing.bump(5.0, s) == pytest.approx(10.5)   # 5.0 >= 25% of 10.5


def test_bump_leaves_below_floor_amount_unchanged_when_too_small():
    s = _settings(min_order_bump=True)
    assert sizing.bump(2.0, s) == pytest.approx(2.0)     # under 25% of 10.5 -- not bumped


def test_bump_off_never_rounds_up():
    s = _settings(min_order_bump=False)
    assert sizing.bump(5.0, s) == pytest.approx(5.0)


def test_bump_passes_through_amounts_already_at_or_above_the_floor():
    s = _settings(min_order_bump=True)
    assert sizing.bump(20.0, s) == pytest.approx(20.0)


# ── liq_distance_pct ─────────────────────────────────────────────────────

def test_liq_distance_pct_isolated_formula():
    # 40x, 1.25% maintenance -> 2.5% - 1.25% = 1.25%
    assert sizing.liq_distance_pct(40, is_cross=False, maint_frac=0.0125) == pytest.approx(1.25)


def test_liq_distance_pct_never_negative():
    assert sizing.liq_distance_pct(50, is_cross=False, maint_frac=0.9) == 0.0


def test_liq_distance_pct_cross_uses_the_same_formula_as_a_documented_estimate():
    # is_cross changes what the number MEANS (see the docstring), not the
    # arithmetic -- same inputs, same output, regardless of is_cross.
    iso = sizing.liq_distance_pct(20, is_cross=False, maint_frac=0.02)
    cross = sizing.liq_distance_pct(20, is_cross=True, maint_frac=0.02)
    assert iso == cross == pytest.approx(3.0)
