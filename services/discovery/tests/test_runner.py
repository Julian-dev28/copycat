from __future__ import annotations

from engine import sizing as real_sizing

from contracts.models import LeverageMode, Settings, SizingMode
from discovery import runner, scoring
from discovery.leaderboard import Candidate

from discovery_fakes import FakeVenue, flat_candles

DAY = 86_400_000
NOW = DAY
M = 60_000


def cand(addr):
    return Candidate(addr, None, 100_000.0, 5_000.0, 10.0, 20_000.0, 60_000.0, False)


def round_trips(coin, n, start=0, gap=10 * M, hold=5 * M, px=100.0):
    out = []
    for i in range(n):
        t = start + i * gap
        out.append({"time_ms": t, "coin": coin, "px": px, "sz": 1.0, "side": "B", "start_position": 0.0,
                    "fee": 0.0, "closed_pnl": 0.0})
        out.append({"time_ms": t + hold, "coin": coin, "px": px, "sz": 1.0, "side": "A", "start_position": 1.0,
                    "fee": 0.0, "closed_pnl": 0.0})
    return out


def score(conn, venue, addr, opts=None, settings=None):
    return runner.score_one_wallet(conn, venue, cand(addr), settings or Settings(), 100.0,
                                   opts or runner.RunOptions(window_days=1, fresh_s=0), real_sizing, NOW)


def test_non_perp_fills_never_reach_candles_and_are_flagged(conn):
    """Regression (coordinator bug 1): '#12100' / '@151' fills made the sim
    call candleSnapshot for them (HL 500)."""
    v = FakeVenue()
    v.set_candles("BTC", "1m", flat_candles(0, NOW, 100.0))
    v.set_fills("0xa", round_trips("BTC", 6) + round_trips("#12100", 3, start=1000) + round_trips("@151", 2, start=2000))
    r = score(conn, v, "0xa")
    assert {c for c, *_ in v.candles_calls} == {"BTC"}
    assert "non_perp_ignored" in r.flags
    assert r.coins == ["BTC"] and r.sim_copies == 6
    assert "too_few_trades" not in r.flags


def test_hft_wallet_is_flagged_and_not_simulated_unless_asked(conn):
    v = FakeVenue()
    v.set_candles("BTC", "1m", flat_candles(0, NOW, 100.0))
    v.set_fills("0xh", round_trips("BTC", 150, gap=6 * M, hold=2 * M))
    r = score(conn, v, "0xh")
    assert "hft" in r.flags and "hft_not_simulated" in r.flags
    assert r.score == scoring.UNSCORED and r.opens_per_day == 150
    assert v.candles_calls == []
    r2 = score(conn, v, "0xh", runner.RunOptions(window_days=1, fresh_s=0, include_hft=True))
    assert "hft" in r2.flags and r2.sim_copies == 150


def test_fills_read_failure_is_flagged_not_fatal(conn):
    v = FakeVenue()
    v.fail_fills.add("0xdead")
    runner.FILLS_RETRY_S = 0.0
    r = score(conn, v, "0xdead")
    assert "error:fills_read_failed" in r.flags and r.score == scoring.UNSCORED
    assert len(v.fills_calls) == runner.FILLS_RETRIES


def test_leverage_max_mode_spends_no_account_state_reads(conn):
    v = FakeVenue()
    v.set_candles("BTC", "1m", flat_candles(0, NOW, 100.0))
    v.set_fills("0xa", round_trips("BTC", 6))
    score(conn, v, "0xa")
    assert v.account_state_calls == 0
    score(conn, v, "0xa", settings=Settings(leverage_mode=LeverageMode.match))
    assert v.account_state_calls == 1


def test_only_trip_spans_get_candles(conn):
    v = FakeVenue()
    v.set_candles("BTC", "1m", flat_candles(0, NOW, 100.0))
    v.set_fills("0xa", round_trips("BTC", 6, start=10 * 60 * M))   # all trips between 10:00 and 11:00
    score(conn, v, "0xa")
    assert all(s >= 10 * 60 * M - M and e <= 11 * 60 * M for _, _, s, e in v.candles_calls)


def test_real_copier_outranks_zero_copy_wallets_end_to_end(conn):
    """Regression (coordinator bugs 3+4) through the whole wallet pipeline."""
    v = FakeVenue()
    rows = flat_candles(0, NOW, 100.0)
    rows[3]["l"] = 1.0    # liquidates the first copy
    v.set_candles("BTC", "1m", rows)
    v.set_fills("0xreal", round_trips("BTC", 11))
    s = Settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=1.0)
    real = score(conn, v, "0xreal", settings=s)
    empty = score(conn, v, "0xempty", settings=s)
    assert real.sim_liquidations == 1 and real.sim_copies == 11
    assert real.score > empty.score == -200.0
    assert all(abs(x.score) < 1e6 for x in (real, empty))


def test_eta():
    assert runner.eta_s(0, 10, 5.0) is None
    assert runner.eta_s(5, 10, 50.0) == 50.0
    assert runner.eta_s(10, 10, 50.0) == 0.0


def test_serial_venue_allows_one_call_in_flight_and_keeps_signatures():
    import inspect
    import threading
    import time as _t

    active, peak = [0], [0]
    lock = threading.Lock()

    class Slow(FakeVenue):
        def fills(self, user, start_ms, end_ms, aggregate_by_time=False):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            _t.sleep(0.01)
            with lock:
                active[0] -= 1
            return []

    sv = runner.SerialVenue(Slow())
    ts = [threading.Thread(target=sv.fills, args=("0x", 0, 1)) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1
    assert "aggregate_by_time" in inspect.signature(sv.fills).parameters


def test_prepare_wallet_cache_only_uses_known_leverage_and_no_venue_calls(conn):
    v = FakeVenue()
    v.set_candles("BTC", "1m", flat_candles(0, NOW, 100.0))
    fills = round_trips("BTC", 6)
    warm = runner.prepare_wallet(conn, v, fills, Settings(), 1, NOW, fresh_s=0)
    assert warm.skip is None and warm.coin_max_lev == {"BTC": 20} and len(warm.events) == 12

    class NoNet(FakeVenue):
        def candles(self, *a):
            return None

        def max_leverage(self, coin):
            raise AssertionError("cache_only must not ask the venue")

    cold = runner.prepare_wallet(conn, NoNet(), fills, Settings(), 1, NOW, coin_max_lev={"BTC": 20},
                                 cache_only=True, fresh_s=0)
    assert cold.flags == [] and len(cold.series["BTC"]) == len(warm.series["BTC"])
    r = runner.simulate_prepared(cold, NoNet(), "0xa", Settings(), 100.0, 1e5, real_sizing, NOW,
                                 curve_step_ms=3_600_000)
    assert r.sim_copies == 6 and r.curve
