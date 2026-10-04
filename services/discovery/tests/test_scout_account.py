from __future__ import annotations

import threading

import pytest
from discovery.scout import account
from discovery.scout import public as scout_public
from test_scout_helpers import DAY, HOUR, NOW, ScoutVenue, addr, portfolio, trips

from contracts.models import AccountSummary

A = addr(7)


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    account.clear_cache()
    scout_public.configure(db_path=tmp_path / "acct.db", venue=None)
    yield
    account.clear_cache()


def _venue():
    v = ScoutVenue()
    v.set_portfolio(A, portfolio([0, 50, -20, 30, 30, 30, -10] * 5, av=20_000.0))
    v.set_fills(A, trips("BTC", 10, NOW - 20 * DAY, every_ms=DAY))
    return v


def test_metrics_fill_every_account_summary_metric_field(tmp_path):
    v = _venue()
    out = account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW)
    for k in ("all_time_pnl_usd", "volume_usd", "longest_win_streak_days", "style", "avg_hold_h",
              "median_hold_h", "pnl_tier", "size_tier", "risk_30d", "trades_30d", "pnl_curve", "value_curve",
              "daily_pnl"):
        assert k in out, k
    assert out["trades_30d"]["trips"] == 10
    assert out["longest_win_streak_days"] == 3
    assert set(out["pnl_curve"]) == {"1d", "7d", "30d", "all"}
    from pydantic import TypeAdapter
    for k, v in out.items():
        if k in AccountSummary.model_fields:      # every value validates as its AccountSummary field type
            TypeAdapter(AccountSummary.model_fields[k].annotation).validate_python(v)


def test_cached_for_five_minutes(tmp_path):
    v = _venue()
    t = [1000.0]
    account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW, clock=lambda: t[0])
    t[0] += 200
    account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW, clock=lambda: t[0])
    assert len(v.portfolio_calls) == 1
    t[0] += 200
    account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW, clock=lambda: t[0])
    assert len(v.portfolio_calls) == 2


def test_slow_fills_time_out_cleanly_and_are_not_cached(tmp_path):
    release = threading.Event()

    class Slow(ScoutVenue):
        def fills(self, user, start_ms, end_ms):
            release.wait(5)
            return []

    v = Slow()
    v.set_portfolio(A, portfolio([1.0] * 10))
    out = account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW, fills_timeout_s=0.05)
    release.set()
    assert out is not None and out["trades_30d"] is None and out["all_time_pnl_usd"] == pytest.approx(9.0)
    account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW)
    assert len(v.portfolio_calls) == 2


def test_failed_portfolio_or_bad_address_is_none(tmp_path):
    v = ScoutVenue()
    assert account.account_metrics(A, v, tmp_path / "a.db", now_ms=NOW) is None
    assert scout_public.account_metrics("not-an-address") is None


def test_public_wrapper_uses_the_configured_venue(tmp_path):
    v = _venue()
    scout_public.configure(db_path=tmp_path / "p.db", venue=v)
    assert scout_public.account_metrics(A.upper().replace("0X", "0x"))["trades_30d"] is not None
    assert HOUR > 0
