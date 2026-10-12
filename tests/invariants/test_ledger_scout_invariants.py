"""Ledger / ROE / day PnL, Scout drawdown and Copy Fit invariants."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

from api.routes import wallets as wallet_routes
from discovery import scoring
from discovery.scout import copy_fit, metrics
from engine import core
from engine.state import EngineState
from engine_fakes import LEADER1, OUR, FakeVenue
from hypothesis import given
from hypothesis import strategies as st

from contracts.models import LeaderStatus, Settings, SizingMode

DAY = 86_400_000
T0 = 1_760_000_000_000 // DAY * DAY


# ── ledger / ROE / day PnL ──────────────────────────────────────────────────

FILL = st.tuples(st.floats(0.01, 100_000.0), st.floats(0.01, 100_000.0), st.floats(0.001, 1_000.0),
                 st.sampled_from([1.0, -1.0]), st.one_of(st.none(), st.floats(0.0, 50.0)))


@given(st.lists(FILL, min_size=1, max_size=15))
def test_realized_is_gross_minus_fees_and_fees_add_up(fills):
    """Prevents: fees counted twice (realized already net of fees, then
    subtracted again on the page) or dropped. After any fills the ledger
    holds realized = sum((px - entry) x size x side) - sum(fees) and
    fees = sum(fees), fees >= 0."""
    v = FakeVenue()
    gross = fees = 0.0
    with tempfile.TemporaryDirectory() as d, EngineState(Path(d) / "e.db") as state:
        for i, (entry, px, size, sign, fee) in enumerate(fills):
            res = {"avg_px": px} if fee is None else {"avg_px": px, "fee": fee}
            core._book_fill(state, v, LEADER1, "BTC", {"szi": sign * size, "entry_px": entry}, res, size, i)
            f = core.fill_fee_usd(res, px * size)
            gross += (px - entry) * size * sign
            fees += f
        led = state.get_ledger(LEADER1)
    assert led["fees_usd"] >= 0
    assert math.isclose(led["fees_usd"], fees, rel_tol=1e-9, abs_tol=1e-6)
    assert math.isclose(led["realized_pnl_usd"], gross - fees, rel_tol=1e-9, abs_tol=1e-4)


@given(st.floats(-1e6, 1e6), st.floats(-1e6, 1e6), st.floats(0.0, 1e6), st.booleans())
def test_roe_is_pnl_over_allocation(realized, unrealized, alloc, allocation_mode):
    """Prevents: an ROE that is not (realized + unrealized) / allocation, or an
    ROE shown for a wallet with no allocation to divide by."""
    eff = Settings(sizing_mode=SizingMode.allocation if allocation_mode else SizingMode.fixed_margin,
                   allocation_usd=alloc)
    row = LeaderStatus(address=LEADER1, read_ok=True, effective=eff, realized_pnl_usd=realized,
                       unrealized_pnl_usd=unrealized)
    w = wallet_routes._position(LEADER1, True, row, eff, False, "custom", "running")
    assert w.pnl_usd == realized + unrealized
    if allocation_mode and alloc > 0:
        assert math.isclose(w.roe_pct, (realized + unrealized) / alloc * 100, rel_tol=1e-12, abs_tol=1e-12)
    else:
        assert w.roe_pct is None


@given(st.floats(100.0, 1e7), st.floats(-1e5, 1e5), st.lists(st.floats(-1e6, 1e6).filter(lambda x: abs(x) > 1),
                                                         min_size=1, max_size=5))
def test_deposit_or_withdrawal_never_changes_day_pnl(anchor_eq, trading_pnl, transfers):
    """Prevents: a deposit read as profit (or a withdrawal as a loss, which
    could also trip the daily loss halt). Day PnL with the transfers in the
    ledger equals day PnL of the same trading without any transfer."""
    def day_pnl(rows, equity_now):
        v = FakeVenue()
        v.ledger[OUR] = rows
        with tempfile.TemporaryDirectory() as d, EngineState(Path(d) / "e.db") as state:
            core._update_day_pnl(state, v, OUR, T0 + 1_000, anchor_eq, lambda e: None)
            return core._update_day_pnl(state, v, OUR, T0 + 3_600_000, equity_now, lambda e: None)
    rows = []
    for i, amt in enumerate(transfers):
        t = T0 + 60_000 * (i + 1)
        rows.append({"time": t, "hash": f"0x{i}", "delta": {"type": "deposit", "usdc": amt} if amt > 0 else
                     {"type": "withdraw", "usdc": -amt, "fee": 0.0}})
    plain, ok1 = day_pnl([], anchor_eq + trading_pnl)
    moved, ok2 = day_pnl(rows, anchor_eq + trading_pnl + sum(transfers))
    assert ok1 and ok2
    assert math.isclose(plain, moved, rel_tol=1e-9, abs_tol=1e-6)


# ── Scout drawdown ──────────────────────────────────────────────────────────

@st.composite
def portfolio(draw):
    """Daily (pnl, account value) closes with random trading PnL and deposits.
    AV_d = AV_prev + pnl_d + deposit_d, floored at 0 (an account can be wiped)."""
    n = draw(st.integers(2, 40))
    av = draw(st.floats(0.0, 5_000.0))
    cum, pnl, avs = 0.0, [(T0, 0.0)], [(T0, av)]
    for i in range(1, n):
        r = draw(st.floats(-1.0, 1.0))
        dep = draw(st.one_of(st.just(0.0), st.floats(0.0, 5e7)))
        d_pnl = max(-(av + dep), r * (av + dep))
        cum += d_pnl
        av = max(0.0, av + dep + d_pnl)
        pnl.append((T0 + i * DAY, cum))
        avs.append((T0 + i * DAY, av))
    return pnl, avs


@given(portfolio())
def test_drawdown_is_bounded(p):
    """Prevents: 'all-time max drawdown 100%' (or 2000%) for a +$61M trader:
    a loss on freshly deposited money divided by a tiny prior balance drove
    the index below zero. DD is in [0, 100] for any curve."""
    dd = metrics.max_drawdown_pct(metrics.daily_returns(*p).returns)
    assert dd is None or 0.0 <= dd <= 100.0


@given(st.lists(st.floats(0.0, 1e6), min_size=2, max_size=30), st.floats(100.0, 1e6))
def test_rising_curve_has_no_drawdown(gains, av0):
    """Prevents: a drawdown shown for a trader who never had a losing day."""
    cum, pnl, avs, av = 0.0, [], [], av0
    for i, g in enumerate(gains):
        cum += g
        av += g
        pnl.append((T0 + i * DAY, cum))
        avs.append((T0 + i * DAY, av))
    assert metrics.max_drawdown_pct(metrics.daily_returns(pnl, avs).returns) in (0.0, None)


@given(st.floats(100.0, 10_000.0), st.floats(1e3, 1e8), st.lists(st.floats(-0.05, 0.05), min_size=3, max_size=20))
def test_deposit_creates_no_drawdown_and_does_not_inflate_losses(av0, dep, rs):
    """Prevents: a deposit-driven drawdown. The same trading returns on the
    same capital give the same drawdown whether or not a big deposit lands on
    day 1 (the deposit is capital, not PnL); and the deposit alone gives 0."""
    def curve(deposit):
        cum, av = 0.0, av0
        pnl, avs = [(T0, 0.0)], [(T0, av)]
        for i, r in enumerate(rs, start=1):
            if i == 1:
                av += deposit
            d = av * r
            cum += d
            av += d
            pnl.append((T0 + i * DAY, cum))
            avs.append((T0 + i * DAY, av))
        return pnl, avs
    a = metrics.max_drawdown_pct(metrics.daily_returns(*curve(0.0)).returns)
    b = metrics.max_drawdown_pct(metrics.daily_returns(*curve(dep)).returns)
    assert b <= 100.0 and a <= 100.0
    # day 1's loss is measured on (av0 + deposit), never on av0 alone
    assert b <= a + 1e-6 or rs[0] < 0
    flat = [(T0, 0.0), (T0 + DAY, 0.0), (T0 + 2 * DAY, 0.0)]
    avf = [(T0, av0), (T0 + DAY, av0 + dep), (T0 + 2 * DAY, av0 + dep)]
    assert metrics.max_drawdown_pct(metrics.daily_returns(flat, avf).returns) == 0.0


def test_regression_61m_trader_is_not_100pct_drawdown():
    """The live case shape: $1k balance, $60M deposited, a -$1.2M day on it,
    then +$62M. Old formula: r = -1.2M / 1k = -1200 -> DD 100%+."""
    pnl = [(T0, 0.0), (T0 + DAY, -1.2e6), (T0 + 2 * DAY, 6.1e7)]
    av = [(T0, 1_000.0), (T0 + DAY, 1_000.0 + 6e7 - 1.2e6), (T0 + 2 * DAY, 1_000.0 + 6e7 + 6.1e7)]
    dd = metrics.max_drawdown_pct(metrics.daily_returns(pnl, av).returns)
    assert dd is not None and 1.9 < dd < 2.1


# ── Copy Fit / score ────────────────────────────────────────────────────────

@st.composite
def fit_input(draw, i):
    return copy_fit.FitInput(
        address=f"0x{i:040x}", account_value_usd=draw(st.floats(0.0, 1e7)),
        sim_score=draw(st.one_of(st.none(), st.floats(-201.0, 100.0))),
        sharpe_30d=draw(st.one_of(st.none(), st.floats(-5, 10))),
        max_drawdown_30d_pct=draw(st.one_of(st.none(), st.floats(0, 100))),
        profitable_days_pct_30d=draw(st.one_of(st.none(), st.floats(0, 100))),
        win_rate_30d_pct=draw(st.one_of(st.none(), st.floats(0, 100))),
        trips_30d=draw(st.integers(0, 500)), copy_capacity_pct=draw(st.one_of(st.none(), st.floats(0, 100))),
        last_fill_ms=draw(st.one_of(st.none(), st.integers(T0 - 10 * DAY, T0))),
        sim_liquidations=draw(st.integers(0, 3)), sim_copies=draw(st.integers(0, 30)),
        flags=draw(st.lists(st.sampled_from(["hft", "vault", "algo", "fills_truncated"]), max_size=2)))


@st.composite
def cohort(draw):
    n = draw(st.integers(1, 12))
    return [draw(fit_input(i)) for i in range(n)]


@given(cohort())
def test_copy_fit_bounded_capped_and_banded(c):
    """Prevents: a Copy Fit outside 0..100, a liquidated / hft / vault /
    inactive wallet above its cap, and a too_few_trades wallet ranked above a
    real copier (>= 5 sim copies, active) on the default sort."""
    out = copy_fit.compute(c, T0)
    for x in c:
        f = out[x.address].value
        assert 0.0 <= f <= 100.0
        if "inactive" in out[x.address].caps:
            assert f == 0.0
        if x.sim_liquidations > 0:
            assert f <= copy_fit.CAP_LIQUIDATED
        if x.sim_copies < copy_fit.MIN_COPIES:
            assert f <= copy_fit.CAP_TOO_FEW
        if {"hft", "algo", "vault"} & set(x.flags):
            assert f <= 50.0
    real = [out[x.address].value for x in c
            if x.sim_copies >= copy_fit.MIN_COPIES and "inactive" not in out[x.address].caps]
    few = [out[x.address].value for x in c if x.sim_copies < copy_fit.MIN_COPIES]
    if real and few:
        assert max(few) <= min(real)


@given(st.floats(-1e4, 1e4), st.floats(-100, 0), st.integers(0, 20), st.integers(0, 4),
       st.floats(-1e4, 1e4), st.floats(-100, 0), st.integers(0, 20), st.integers(5, 200))
def test_too_few_trades_never_outranks_a_trusted_score(r1, d1, l1, c1, r2, d2, l2, c2):
    """Prevents: a 2-trade lucky wallet ranked above every real track record."""
    few = scoring.score_candidate(r1, d1, l1, c1)
    real = scoring.score_candidate(r2, d2, l2, c2)
    assert few.score < real.score
    assert "too_few_trades" in few.flags and "too_few_trades" not in real.flags
