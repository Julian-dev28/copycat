"""Preview == engine: what the Trade ticket / MCP plan shows is what
engine.core does on its next cycle, for the same inputs.

engine.public.preview_wallet (plan_allocation / plan_copy) against a real
core.run_cycle on a FakeVenue with the same leader book, mids, max leverage
and settings. Our account is huge (margin room never binds, which the
preview does not model and says so in a note).
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from unittest import mock

from engine import core, public, sizing
from engine.state import EngineState
from engine_fakes import LEADER1, OUR, FakeVenue
from hypothesis import given
from hypothesis import strategies as st

from contracts.models import (
    EngineStatus,
    ExposureMode,
    LeverageMode,
    Settings,
    SizingMode,
    SmallAccountMode,
    TradeDirection,
    WalletCopyRequest,
)

COINS = ["AAA", "BTC", "ETH", "NEAR", "SOL", "xyz:TSLA"]
OUR_EQUITY = 1e9


@st.composite
def scenario(draw):
    coins = draw(st.lists(st.sampled_from(COINS), min_size=1, max_size=6, unique=True))
    book, mids, maxes = {}, {}, {}
    for c in coins:
        entry = draw(st.floats(0.5, 50_000.0))
        ntl = draw(st.floats(50.0, 3_000_000.0))
        side = draw(st.sampled_from([1.0, -1.0]))
        book[c] = {"szi": side * ntl / entry, "entry_px": entry, "lev": float(draw(st.integers(1, 40)))}
        mids[c] = entry * draw(st.sampled_from([1.0, 0.97, 1.03, 0.6, 1.6, 2.2]))
        maxes[c] = draw(st.sampled_from([3, 5, 10, 20, 40, 50]))
    allocation = draw(st.booleans())
    common = dict(
        trade_direction=draw(st.sampled_from(list(TradeDirection))),
        max_worse_entry_pct=draw(st.sampled_from([0.0, 2.0, 10.0, 50.0])),
        coin_blocklist=draw(st.lists(st.sampled_from(COINS), max_size=2)),
        leverage_mode=draw(st.sampled_from(list(LeverageMode))),
        leverage=draw(st.integers(1, 50)),
    )
    if allocation:
        exp = draw(st.sampled_from(list(ExposureMode)))
        req = WalletCopyRequest(
            settings_source="custom", allocation_usd=draw(st.floats(5.0, 200_000.0)), exposure_mode=exp,
            target_leverage=draw(st.integers(1, 50)) if exp == ExposureMode.target else None,
            small_account_mode=draw(st.sampled_from(list(SmallAccountMode))), **common)
        base = Settings(max_open_copies=draw(st.integers(1, 6)),
                        max_position_leverage=draw(st.integers(1, 50)))
    else:
        req = WalletCopyRequest(settings_source="global")
        base = Settings(sizing_mode=draw(st.sampled_from([SizingMode.fixed_margin, SizingMode.fixed_notional,
                                                          SizingMode.proportional])),
                        fixed_margin_usd=draw(st.floats(0.5, 2_000.0)),
                        fixed_notional_usd=draw(st.floats(10.5, 50_000.0)),
                        size_multiplier=draw(st.floats(0.0, 3.0)), sleeve_frac=draw(st.floats(0.0, 1.0)),
                        min_order_bump=draw(st.booleans()),
                        small_account_mode=draw(st.sampled_from(list(SmallAccountMode))),
                        max_open_copies=draw(st.integers(1, 6)),
                        max_position_leverage=draw(st.integers(1, 50)), **common)
    base = base.model_copy(update={"leaders": [LEADER1]})
    his_eq = draw(st.floats(1_000.0, 50_000_000.0))
    return book, mids, maxes, req, base, his_eq


def _venue(book, mids, maxes, his_eq) -> FakeVenue:
    v = FakeVenue()
    v.set_account(OUR, OUR_EQUITY, available={"": OUR_EQUITY, "xyz": OUR_EQUITY})
    v.set_account(LEADER1, his_eq, available={"": his_eq})
    for c, p in book.items():
        v.hold(LEADER1, c, p["szi"], entry_px=p["entry_px"], lev=p["lev"], equity_perp_usd=his_eq)
    v.mids.update(mids)
    v.max_levs.update(maxes)
    return v


def _preview(book, mids, maxes, req, base, his_eq):
    st_ = EngineStatus(running=True, enabled=True, dry_run=False, equity_usd=OUR_EQUITY,
                       available_margin_usd=OUR_EQUITY, positions=[], leaders=[])
    with mock.patch.object(public, "status", lambda *a, **k: st_):
        return public.preview_wallet(LEADER1, req, base, venue=_venue(book, mids, maxes, his_eq), now_ms=0)


def _engine(book, mids, maxes, req, base, his_eq):
    es = public.wallet_settings(base, LEADER1, req)
    es = es.model_copy(update={"enabled": True, "dry_run": False, "leaders": [LEADER1],
                               "leader_overrides": {}, "only_new_positions": False, "one_shot": False})
    v = _venue(book, mids, maxes, his_eq)
    with tempfile.TemporaryDirectory() as d, EngineState(Path(d) / "e.db") as state:
        out = core.run_cycle(es, v, state, OUR, 0, lambda e: None)
    return v, out


@given(scenario())
def test_preview_status_and_size_equal_the_engines_next_cycle(sc):
    """Prevents: a preview / MCP plan row marked "copy" with a notional the
    engine never opens (NEAR: their entry 2.35, mid 5.25, 2% allowed -> the
    engine waits forever; the plan said copy), or opens at a different size,
    leverage or side; and totals that count slices the engine will not place.
    Statuses map: copy/trimmed/bump <-> an order of that notional at that
    leverage and side; wait <-> the engine's worse-entry skip; skip <-> no order."""
    book, mids, maxes, req, base, his_eq = sc
    pv = _preview(*sc)
    v, out = _engine(*sc)
    orders = {o[0]: o for o in v.orders}
    for s in pv.slices:
        if s.status in ("copy", "trimmed", "bump"):
            assert s.coin in orders, (s, out["skipped"].get(s.coin))
            coin, is_buy, size, _ = orders[s.coin]
            assert math.isclose(size * mids[coin], s.notional_usd, rel_tol=1e-4, abs_tol=mids[coin] * 2e-6)
            assert v.levs[coin]["leverage"] == s.leverage
            assert is_buy == (s.side == "long")
            assert math.isclose(s.margin_usd, s.notional_usd / s.leverage, rel_tol=1e-9)
        else:
            assert s.coin not in orders, (s, orders.get(s.coin))
            assert s.notional_usd == 0.0 and s.margin_usd == 0.0
            if s.status == "wait":
                assert "worse than entry" in out["skipped"].get(s.coin, ""), out["skipped"].get(s.coin)
    live = [s for s in pv.slices if s.status not in sizing.NOT_COPIED]
    assert pv.copied == len(live) == len(orders)
    assert pv.waiting == sum(1 for s in pv.slices if s.status == "wait")
    assert math.isclose(pv.planned_margin_usd, sum(s.margin_usd for s in live), rel_tol=1e-9, abs_tol=1e-9)


@given(scenario())
def test_counter_preview_is_copy_with_every_side_inverted(sc):
    """Prevents: a counter preview whose sizes differ from the copy preview
    (direction must never change size), or a side that is not inverted."""
    book, _mids, maxes, req, base, his_eq = sc
    # equal sizes need the same worse-entry outcome on both sides: mid at his entry
    mids = {c: p["entry_px"] for c, p in book.items()}
    if req.settings_source == "custom":
        mk = lambda d: req.model_copy(update={"trade_direction": d, "max_worse_entry_pct": 100.0})  # noqa: E731
        a = _preview(book, mids, maxes, mk(TradeDirection.copy), base, his_eq)
        b = _preview(book, mids, maxes, mk(TradeDirection.counter), base, his_eq)
    else:
        mk = lambda d: base.model_copy(update={"trade_direction": d, "max_worse_entry_pct": 100.0})  # noqa: E731
        a = _preview(book, mids, maxes, req, mk(TradeDirection.copy), his_eq)
        b = _preview(book, mids, maxes, req, mk(TradeDirection.counter), his_eq)
    for x, y in zip(a.slices, b.slices, strict=True):
        assert (x.coin, x.status, x.notional_usd, x.leverage) == (y.coin, y.status, y.notional_usd, y.leverage)
        assert x.side != y.side
    assert a.planned_notional_usd == b.planned_notional_usd


def test_near_regression_far_from_entry_waits_and_is_not_in_the_totals():
    """The MCP run that found it: NEAR their entry 2.35, mid ~5.25, 2% allowed."""
    book = {"NEAR": {"szi": 10_000.0, "entry_px": 2.35, "lev": 5.0},
            "BTC": {"szi": 1.0, "entry_px": 60_000.0, "lev": 5.0}}
    mids = {"NEAR": 5.25, "BTC": 60_000.0}
    req = WalletCopyRequest(settings_source="custom", allocation_usd=1_000.0, exposure_mode=ExposureMode.target,
                            target_leverage=3, max_worse_entry_pct=2.0)
    sc = (book, mids, {"NEAR": 10, "BTC": 40}, req, Settings(leaders=[LEADER1]), 500_000.0)
    pv = _preview(*sc)
    near = next(s for s in pv.slices if s.coin == "NEAR")
    assert near.status == "wait" and near.notional_usd == 0.0
    assert "123.4% past their entry; opens only within 2%" in near.reason
    assert pv.waiting == 1 and pv.copied == 1
    v, _ = _engine(*sc)
    assert [o[0] for o in v.orders] == ["BTC"]
    assert any("waiting on price: NEAR" in n for n in pv.notes)
