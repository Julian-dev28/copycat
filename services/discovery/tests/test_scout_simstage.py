"""Scout stage C (simstage.simulate) runs the exact /discover pipeline
(runner.prepare_wallet + runner.simulate_prepared) and gets its hourly sim
curve from ONE sim run (curve_step_ms=1h, window_start_ms=window start)."""
from __future__ import annotations

import pytest
from discovery import runner, sim
from discovery.scout import config as C
from discovery.scout import simstage
from discovery_fakes import FakeVenue
from engine import sizing as real_sizing

from contracts.models import LeverageMode, Settings

DAY = C.DAY_MS
HOUR = 3_600_000
M = 60_000
NOW = 30 * DAY + 7 * M          # not on an hour boundary: the last curve point is `now` itself
WS = NOW - C.WINDOW_DAYS * DAY
EQ = 100.0
LEADER_EQ = 50_000.0


def ramp(start_ms, end_ms, p0, p1, step_ms=M):
    out, t, n = [], start_ms, max(1, (end_ms - start_ms) // step_ms)
    while t <= end_ms:
        px = p0 + (p1 - p0) * ((t - start_ms) // step_ms) / n
        out.append({"t": t, "o": px, "h": px * 1.001, "l": px * 0.999, "c": px, "v": 0.0})
        t += step_ms
    return out


def trips(coin, starts, hold, px_in, px_out, size=10.0):
    out = []
    for t in starts:
        out.append({"time_ms": t, "coin": coin, "px": px_in, "sz": size, "side": "B", "start_position": 0.0,
                    "fee": 0.0, "closed_pnl": 0.0})
        out.append({"time_ms": t + hold, "coin": coin, "px": px_out, "sz": size, "side": "A",
                    "start_position": size, "fee": 0.0, "closed_pnl": 0.0})
    return out


def world():
    v = FakeVenue()
    v.set_candles("BTC", "1m", ramp(NOW - 3 * DAY, NOW, 100.0, 130.0))
    v.set_candles("ETH", "1m", ramp(NOW - 3 * DAY, NOW, 50.0, 40.0))
    fills = (trips("BTC", [NOW - 3 * DAY + i * 6 * HOUR for i in range(8)], 4 * HOUR, 100.0, 104.0)
             + trips("ETH", [NOW - 2 * DAY + i * 5 * HOUR for i in range(6)], 3 * HOUR, 48.0, 47.0, size=20.0))
    return v, sorted(fills, key=lambda f: f["time_ms"])


def via_runner(conn, v, fills, settings, lev_by_coin=None, **kw):
    """What /discover does for the same wallet (score_one_wallet's two steps)."""
    p = runner.prepare_wallet(conn, v, fills, settings, C.WINDOW_DAYS, NOW, fresh_s=0)
    if lev_by_coin is not None:
        v.set_account_state("0xw", {"positions": {c: {"lev": x} for c, x in lev_by_coin.items()}})
    return p, runner.simulate_prepared(p, v, "0xw", settings, EQ, LEADER_EQ, real_sizing, NOW, **kw)


def scout(conn, v, fills, settings, lev_by_coin=None):
    return simstage.simulate(conn, v, fills, settings, EQ, LEADER_EQ, lev_by_coin or {}, NOW, real_sizing)


def test_scout_and_discover_simulate_identically(conn):
    v, fills = world()
    out = scout(conn, v, fills, Settings())
    _, r = via_runner(conn, v, fills, Settings())
    f = out.fields
    assert f["simulated"] is True and r.sim_copies == 10
    assert r.flags.count("worse_entry:BTC") == 4                 # skip flags survive simulate_prepared
    assert f["sim_copy_capacity_pct"] == pytest.approx(10 / 14 * 100, abs=1e-3)
    assert f["sim_return_pct"] == pytest.approx(round(r.sim_return_pct, 4))
    assert f["sim_return_pct"] != 0.0
    assert f["sim_max_drawdown_pct"] == pytest.approx(round(r.sim_max_drawdown_pct, 4))
    assert (f["sim_copies"], f["sim_liquidations"], f["sim_skipped_min_order"]) == (
        r.sim_copies, r.sim_liquidations, r.sim_skipped_min_order)
    assert f["sim_fees_usd"] == pytest.approx(round(r.sim_fees_usd, 6))
    assert f["coins"] == ["BTC", "ETH"] and f["fills_30d"] == len(fills)
    assert out.coin_max_lev == {"BTC": 20, "ETH": 20}
    # capacity ~71% (10 of 14) is below the note threshold: the dominant (only) skip
    # reason here is worse_entry, all 4 of them -> 100% share of the skips shown.
    assert f["sim_capacity_note"] == "100% of skipped opens: price had already moved past your worse-entry limit"


def test_capacity_reason_dominant_cause_and_threshold():
    """user_consensus P0 #2: one plain-language line naming the dominant
    skip reason, only when capacity is actually low."""
    # no skips at all: nothing to explain
    assert simstage.capacity_reason(10, 0, []) is None
    # capacity 9/10 = 90% >= CAPACITY_NOTE_MAX_PCT (80): still nothing to explain
    assert simstage.capacity_reason(9, 1, []) is None
    # capacity 4/10 = 40%, all from the $10.50 minimum
    assert simstage.capacity_reason(4, 6, []) == "100% of skipped opens: under the $10.50 minimum order at your size"
    # mixed: 2 min-order + 6 worse_entry = 8 skips, worse_entry dominates (75% of the 8)
    note = simstage.capacity_reason(2, 2, ["worse_entry:BTC"] * 6)
    assert note == "75% of skipped opens: price had already moved past your worse-entry limit"
    # capacity 0 (no copies, no skips): nothing to explain either (den == 0)
    assert simstage.capacity_reason(0, 0, []) is None


def test_leverage_match_uses_stored_leverage_like_discover_reads_it(conn):
    s = Settings(leverage_mode=LeverageMode.match)
    lev = {"BTC": 3.0, "ETH": 7.0}
    v, fills = world()
    out = scout(conn, v, fills, s, lev)
    calls_before = v.account_state_calls
    _, r = via_runner(conn, v, fills, s, lev)
    assert v.account_state_calls == calls_before + 1        # discover reads it live...
    assert calls_before == 0                                 # ...Scout never does: stage B stored it
    assert out.fields["sim_return_pct"] == pytest.approx(round(r.sim_return_pct, 4))
    assert out.fields["sim_fees_usd"] == pytest.approx(round(r.sim_fees_usd, 6))
    low = scout(conn, v, fills, s, {"BTC": 1.0, "ETH": 1.0})
    assert low.fields["sim_return_pct"] != out.fields["sim_return_pct"]   # the leverage really reaches the sim


def test_hourly_curve_comes_from_one_sim_run(conn, monkeypatch):
    v, fills = world()
    runs = []
    real = sim.simulate_wallet

    def spy(*a, **kw):
        runs.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(sim, "simulate_wallet", spy)
    out = scout(conn, v, fills, Settings())
    assert len(runs) == 1                                   # was 1 + 30 daily prefix runs
    assert runs[0]["curve_step_ms"] == HOUR and runs[0]["window_start_ms"] == WS
    ts = [p.t_ms for p in out.curve]
    assert ts[0] == (WS // HOUR) * HOUR and ts[-1] == NOW
    assert all(b - a == HOUR for a, b in zip(ts[:-2], ts[1:-1], strict=True))
    assert len(ts) == C.WINDOW_DAYS * 24 + 2               # hours 0..720 from the floored start, + now
    first_event = fills[0]["time_ms"]
    assert all(p.value == EQ for p in out.curve if p.t_ms < first_event)   # flat before his first trade
    final = EQ * (1 + out.fields["sim_return_pct"] / 100.0)
    assert out.curve[-1].value == pytest.approx(final, abs=1e-3)


def test_hourly_curve_matches_prefix_runs(conn):
    """The property the old 30 prefix runs relied on: the sim is causal, so
    a run over events <= T ending at T ends at the curve's value at T."""
    v, fills = world()
    out = scout(conn, v, fills, Settings())
    p, _ = via_runner(conn, v, fills, Settings())
    at = {pt.t_ms: pt.value for pt in out.curve}
    checked = 0
    for t in range(NOW - 3 * DAY + HOUR, NOW, 7 * HOUR):
        t = (t // HOUR) * HOUR
        r = sim.simulate_wallet(events=[e for e in p.events if e.time_ms < t], series=p.series,
                                coin_max_lev=p.coin_max_lev, leader_equity_usd=LEADER_EQ,
                                leader_leverage_by_coin={}, settings=Settings(), sim_equity_usd=EQ,
                                window_end_ms=t, sizing=real_sizing)
        assert at[t] == pytest.approx(EQ * (1 + r.sim_return_pct / 100.0), abs=1e-3), t
        checked += 1
    assert checked >= 9


def test_skip_flags_match_discover(conn):
    v = FakeVenue()
    # > 100 opens/day over the 30d window = > 3000 opens; 25s apart, 10s holds (poll 5s keeps them apart)
    hft = trips("BTC", [NOW - DAY + i * 25_000 for i in range(3100)], 10_000, 100.0, 100.0, size=1.0)
    out = scout(conn, v, hft, Settings())
    p = runner.prepare_wallet(conn, v, hft, Settings(), C.WINDOW_DAYS, NOW, fresh_s=0)
    assert out.fields["simulated"] is False and out.curve == []
    assert out.fields["flags"] == sorted(set(p.flags + p.skip)) == ["hft", "hft_not_simulated"]
    assert v.candles_calls == []
    few = scout(conn, v, [], Settings())
    assert few.fields["flags"] == ["too_few_trades"] and few.fields["simulated"] is False


def test_what_if_cache_only_reuses_stage_c_bars(conn):
    v, fills = world()
    full = scout(conn, v, fills, Settings())
    n = len(v.candles_calls)
    again = simstage.simulate(conn, simstage.CacheOnlyVenue(), fills, Settings(), EQ, LEADER_EQ, {}, NOW,
                              real_sizing, coin_max_lev=full.coin_max_lev, cache_only=True)
    assert len(v.candles_calls) == n
    assert again.fields["sim_return_pct"] == full.fields["sim_return_pct"]
    assert [p.value for p in again.curve] == [p.value for p in full.curve]
    assert not any(f.startswith("candles_partial") for f in again.fields["flags"])
