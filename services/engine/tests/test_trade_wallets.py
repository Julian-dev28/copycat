"""Trade page wallets through engine.core.run_cycle: allocation sizing,
the allocation cap, concentrate on a $20 wallet, liquidity splits with
catch-up, the realized-PnL ledger, stop-one-wallet and read-budget pacing.
FakeVenue only, hand-computed numbers in the comments."""
from __future__ import annotations

import json

import pytest
from engine import core
from engine_fakes import LEADER1, LEADER2, OUR

from contracts.models import Settings


def wallet(leaders=(LEADER1,), **kw) -> Settings:
    base = dict(enabled=True, dry_run=False, leaders=list(leaders), sizing_mode="allocation",
                allocation_usd=1000.0, exposure_mode="match", target_leverage=5,
                leverage_mode="max", max_worse_entry_pct=10.0, small_account_mode="concentrate")
    base.update(kw)
    return Settings(**base)


def run(venue, settings, state, now_ms=0, stops=None):
    events = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append, stops=stops)
    out["_events"] = events
    return out


# ── sizing in the cycle ─────────────────────────────────────────────────────

def test_match_mode_open(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)            # $100k on his $1M
    out = run(venue, wallet(), engine_state)
    # 100k / 1M * 1000 = $100 -> 1.0 BTC at mid 100, at the coin max (leverage_mode max)
    assert out["opened"] == ["BTC"]
    assert venue.orders == [("BTC", True, 1.0, False)]
    assert venue.levs["BTC"]["leverage"] == 50


def test_target_mode_spreads_allocation_times_leverage_in_his_proportions(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 750.0, entry_px=100.0)             # $75k
    venue.hold(LEADER1, "ETH", -250.0, entry_px=100.0)            # $25k short
    out = run(venue, wallet(exposure_mode="target"), engine_state)
    # BTC 0.75 * 1000 * 5 = $3,750 -> 37.5; ETH 0.25 * 1000 * 5 = $1,250 -> 12.5 short
    assert sorted(out["opened"]) == ["BTC", "ETH"]
    assert sorted(venue.orders) == [("BTC", True, 37.5, False), ("ETH", False, 12.5, False)]
    assert venue.levs["BTC"]["leverage"] == 5 and venue.levs["ETH"]["leverage"] == 5


def test_target_mode_leverage_capped_by_coin_max_keeps_margin_at_the_slice(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 3
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, wallet(exposure_mode="target"), engine_state)
    # lev min(5, 3) = 3; 1.0 * 1000 * 3 = $3,000 -> 30 BTC, margin $1,000
    assert venue.levs["BTC"]["leverage"] == 3
    assert venue.orders == [("BTC", True, 30.0, False)]


def _btc_then_eth(engine_state, venue, our_btc: float):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)            # $100k, his whole book
    s = wallet(exposure_mode="target")
    run(venue, s, engine_state)                                     # $5,000 -> 50 BTC at 5x
    assert venue.orders == [("BTC", True, 50.0, False)]
    venue.hold(OUR, "BTC", our_btc, entry_px=100.0, equity_perp_usd=100_000.0,
               available={"": 100_000.0})
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)            # +$100k: gross now $200k
    return run(venue, s, engine_state, now_ms=1)


def test_allocation_cap_trims_the_order_to_fit(engine_state, venue):
    out = _btc_then_eth(engine_state, venue, 50.0)
    # ETH wants 0.5 * 1000 * 5 = $2,500, but BTC holds 50 * 100 / 5 = $1,000 of margin:
    # room (1020 - 1000) * 5 = $100 -> 1.0 ETH
    assert out["opened"] == ["ETH"]
    assert venue.orders[-1] == ("ETH", True, 1.0, False)


def test_allocation_cap_skips_when_the_trim_is_under_the_minimum(engine_state, venue):
    out = _btc_then_eth(engine_state, venue, 50.95)
    # margin 50.95 * 100 / 5 = $1,019 -> room $1 * 5 = $5 < $10.50
    assert "ETH" not in out["opened"]
    assert out["skipped"]["ETH"].startswith("allocation full")


def test_reductions_are_unaffected_by_allocation(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, wallet(), engine_state)
    venue.hold(OUR, "BTC", 1.0, entry_px=100.0, equity_perp_usd=100_000.0)
    venue.hold(LEADER1, "BTC", 250.0, entry_px=100.0)             # he takes 75% off
    out = run(venue, wallet(), engine_state, now_ms=1)
    assert out["reduced"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", False, 0.75, True)


# ── the $20 wallet copying a 15-position whale ──────────────────────────────

WHALE_K = [300, 200, 100, 100, 50, 50, 50, 30, 30, 30, 20, 20, 10, 5, 5]


def test_twenty_dollar_wallet_concentrates_into_his_top_four(engine_state, venue):
    venue.set_account(OUR, 25.0, available={"": 25.0})
    for i, k in enumerate(WHALE_K):
        venue.hold(LEADER1, f"C{i + 1:02d}", k * 10.0, entry_px=100.0)   # k thousand USD
    out = run(venue, wallet(allocation_usd=20.0, exposure_mode="target"), engine_state)
    # $20 at 5x = $100 over his top 4 (700k): 42.86, 28.57, 14.29, 14.29 -> margin $20
    assert sorted(out["opened"]) == ["C01", "C02", "C03", "C04"]
    sizes = {o[0]: o[2] for o in venue.orders}
    assert sizes["C01"] == pytest.approx(300 / 700 * 100 / 100, abs=1e-6)
    assert sizes["C04"] == pytest.approx(100 / 700 * 100 / 100, abs=1e-6)
    assert "concentrate" in out["skipped"]["C05"]


def test_bump_and_skip_modes_in_the_cycle(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER1, "ETH", 50.0, entry_px=100.0)              # $5k of a $105k book
    s = wallet(allocation_usd=20.0, exposure_mode="target", small_account_mode="skip")
    out = run(venue, s, engine_state)
    # BTC 100/105 * 100 = $95.24; ETH 5/105 * 100 = $4.76 < 10.50 -> skipped
    assert out["opened"] == ["BTC"]


# ── liquidity: a $1M account into a thin xyz coin ──────────────────────────

THIN = "xyz:THIN"


def test_large_order_splits_and_catches_up_over_cycles(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0, available={"": 1_000_000.0, "xyz": 1_000_000.0})
    venue.hold(LEADER1, THIN, 50_000.0, entry_px=100.0, equity_perp_usd=10_000_000.0)  # $5M
    venue.day_volume[THIN] = 20_000_000.0       # 0.5% = $100k
    venue.depth[THIN] = 80_000.0                # depth wins: $80k per order
    s = wallet(allocation_usd=500_000.0)
    out = run(venue, s, engine_state)
    # 5M / 10M * 500k = $250k: 80k now, 170k carried
    assert venue.orders == [(THIN, True, 800.0, False)]
    assert out["split"] == [THIN]
    assert any(e.action == "open" and "split" in (e.reason or "") for e in out["_events"])
    held = 800.0
    for t, want in ((1, 800.0), (2, 800.0), (3, 100.0)):          # 80k, 80k, then the last 10k
        venue.hold(OUR, THIN, held, entry_px=100.0, equity_perp_usd=1_000_000.0)
        run(venue, s, engine_state, now_ms=t)
        assert venue.orders[-1] == (THIN, True, want, False)
        held += want
    n = len(venue.orders)
    venue.hold(OUR, THIN, held, entry_px=100.0, equity_perp_usd=1_000_000.0)
    run(venue, s, engine_state, now_ms=4)
    assert len(venue.orders) == n                                  # filled: nothing more


def test_catch_up_is_dropped_when_he_changes_the_position(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0, available={"": 1_000_000.0, "xyz": 1_000_000.0})
    venue.hold(LEADER1, THIN, 50_000.0, entry_px=100.0, equity_perp_usd=10_000_000.0)
    venue.depth[THIN] = 80_000.0
    s = wallet(allocation_usd=500_000.0)
    run(venue, s, engine_state)
    venue.hold(OUR, THIN, 800.0, entry_px=100.0, equity_perp_usd=1_000_000.0)
    venue.hold(LEADER1, THIN, 40_000.0, entry_px=100.0, equity_perp_usd=10_000_000.0)  # he trims
    out = run(venue, s, engine_state, now_ms=1)
    assert out["reduced"] == [THIN]
    assert all(o[3] for o in venue.orders[1:])                     # only the reduce went out
    assert not engine_state.get_kv("catch_up")


def test_failed_liquidity_reads_send_small_orders_and_hold_big_ones(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.depth["BTC"] = None
    out = run(venue, wallet(), engine_state)                       # $100 < $50k: uncapped
    assert out["opened"] == ["BTC"]
    venue.hold(LEADER2, "ETH", 10_000.0, entry_px=100.0)          # $1M on his $1M
    venue.depth["ETH"] = None
    out = run(venue, wallet(leaders=(LEADER1, LEADER2), allocation_usd=100_000.0), engine_state,
              now_ms=1)
    assert "uncapped limit" in out["skipped"]["ETH"]               # $100k, pending
    venue.depth["ETH"] = 1e12
    out = run(venue, wallet(leaders=(LEADER1, LEADER2), allocation_usd=100_000.0), engine_state,
              now_ms=2)
    assert out["opened"] == ["ETH"]


def test_market_orders_carry_max_slippage_pct(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, wallet(max_slippage_pct=0.4), engine_state)
    assert venue.slippages == [0.4]


# ── ledger ──────────────────────────────────────────────────────────────────

def _open_one_btc(engine_state, venue, **kw):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    s = wallet(**kw)
    run(venue, s, engine_state)                                     # 1.0 BTC
    venue.hold(OUR, "BTC", 1.0, entry_px=100.0, equity_perp_usd=100_000.0, unrealized_pnl=3.0)
    return s


def test_ledger_books_reduce_and_close_and_status_shows_the_wallet(engine_state, venue):
    s = _open_one_btc(engine_state, venue, invested_ms=0)
    out = run(venue, s, engine_state, now_ms=1)
    row = out["leaders"][0]
    # one copy, $100 at 50x: margin $2, uPnL $3 from the raw position
    assert (row.open_copies, row.exposure_usd, row.margin_used_usd, row.unrealized_pnl_usd) == (
        1, 100.0, 2.0, 3.0)
    venue.mids["BTC"] = 110.0
    venue.hold(LEADER1, "BTC", 500.0, entry_px=100.0)             # he halves
    run(venue, s, engine_state, now_ms=2)                           # we sell 0.5 at 110: +$5
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0, equity_perp_usd=100_000.0)
    venue.close_fill_px["BTC"] = 120.0
    venue.hold(LEADER1, "BTC", 0.0)                                 # he closes
    out = run(venue, s, engine_state, now_ms=3)                     # 0.5 at 120: +$10
    assert out["closed"] == ["BTC"]
    # +$5 and +$10 gross, minus taker-rate fee estimates on the open and both exits
    # (HL order responses carry no fee): fees_usd is exactly that sum.
    lead = out["leaders"][0]
    assert lead.fees_usd > 0
    assert lead.realized_pnl_usd == pytest.approx(15.0 - lead.fees_usd)
    assert out["leaders"][0].open_copies == 0


def test_ledger_resets_on_a_fresh_investment_and_ignores_fills_before_it(engine_state):
    engine_state.sync_ledger(LEADER1, 100)
    assert engine_state.book_pnl(LEADER1, 7.0, 0.0, now_ms=150)
    assert not engine_state.book_pnl(LEADER1, 99.0, 0.0, now_ms=50)    # before invested_ms
    engine_state.sync_ledger(LEADER1, 100)                              # same investment: kept
    assert engine_state.get_ledger(LEADER1)["realized_pnl_usd"] == 7.0
    engine_state.sync_ledger(LEADER1, 200)                              # reinvest: reset
    assert engine_state.get_ledger(LEADER1)["realized_pnl_usd"] == 0.0


def test_fees_are_subtracted_when_the_fill_reports_them(engine_state, venue):
    pos = {"szi": -2.0, "entry_px": 100.0}                          # short 2 at 100
    core._book_fill(engine_state, venue, LEADER1, "ETH", pos, {"avg_px": 90.0, "fee": 0.25}, 2.0, 1)
    led = engine_state.get_ledger(LEADER1)
    # (90 - 100) * 2 * -1 = +20, minus 0.25
    assert led["realized_pnl_usd"] == pytest.approx(19.75) and led["fees_usd"] == pytest.approx(0.25)


# ── stop one wallet ─────────────────────────────────────────────────────────

def test_stop_with_close_retries_until_flat_then_finishes(engine_state, venue):
    s = _open_one_btc(engine_state, venue)
    gone = s.model_copy(update={"leaders": []})                     # the api removed him
    venue.fail_close = True
    out = run(venue, gone, engine_state, now_ms=1, stops={LEADER1: True})
    assert out["stops_done"] == []
    row = {r.address: r for r in out["leaders"]}[LEADER1]
    assert row.stopping and row.open_copies == 1                    # orphan, winding down
    venue.fail_close = False
    out = run(venue, gone, engine_state, now_ms=2, stops={LEADER1: True})
    assert out["stops_done"] == [LEADER1] and out["closed"] == ["BTC"]
    reasons = [(e.action, e.reason) for e in out["_events"] if e.leader == LEADER1]
    assert ("close", "stop wallet") in reasons and ("skip", "wallet stopped") in reasons
    assert engine_state.get_copy("BTC") is None


def test_stop_without_close_leaves_copies_to_follow_his_exits(engine_state, venue):
    s = _open_one_btc(engine_state, venue)
    gone = s.model_copy(update={"leaders": []})
    out = run(venue, gone, engine_state, now_ms=1, stops={LEADER1: False})
    assert out["stops_done"] == [LEADER1] and not venue.closes
    venue.hold(LEADER1, "BTC", 0.0)
    out = run(venue, gone, engine_state, now_ms=2)
    assert out["closed"] == ["BTC"]                                  # orphan exit mirrored


def test_a_stopped_wallet_still_in_settings_gets_no_new_exposure(engine_state, venue):
    s = _open_one_btc(engine_state, venue)
    venue.fail_close = True
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)
    out = run(venue, s, engine_state, now_ms=1, stops={LEADER1: True})
    assert "ETH" not in out["opened"]


# ── pacing ──────────────────────────────────────────────────────────────────

def test_25_leaders_report_the_stretched_poll(engine_state, venue):
    leaders = ["0x" + f"{i:040x}" for i in range(1, 26)]
    venue.set_account(OUR, 1000.0)
    for a in leaders:
        venue.set_account(a, 1000.0)
    out = run(venue, wallet(leaders=leaders, enabled=False), engine_state)
    # 26 accounts x 4 + allMids 2 = 106 -> 106 * 60 / 720
    assert out["read_weight"] == 106
    assert out["effective_poll_s"] == pytest.approx(round(106 * 60 / 720, 3))


# ── public: stop flags, status, preview ─────────────────────────────────────

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", OUR)
    return tmp_path


def test_public_reads_and_clears_stop_flags(data_dir, venue):
    from engine import public
    (data_dir / "settings.json").write_text(json.dumps(wallet(leaders=[]).model_dump(mode="json")))
    (data_dir / "stop").mkdir()
    (data_dir / "stop" / f"{LEADER1}.flag").write_text(json.dumps({"close_positions": True}))
    (data_dir / "stop" / "junk.flag").write_text("{}")
    assert public.read_stops() == {LEADER1: True}
    venue.set_account(OUR, 1000.0)
    public.run_cycle(venue, now_ms=1)
    assert not (data_dir / "stop" / f"{LEADER1}.flag").exists()
    st = public.status()
    assert st.effective_poll_s == pytest.approx(5.0)


def test_preview_matches_the_plan_for_the_whale(data_dir, venue):
    from engine import public

    from contracts.models import WalletCopyRequest
    for i, k in enumerate(WHALE_K):
        venue.hold(LEADER1, f"C{i + 1:02d}", k * 10.0, entry_px=100.0)
    venue.depth["C01"] = 20.0                                      # $42.86 at $20 a cycle: 3
    req = WalletCopyRequest(allocation_usd=20.0, exposure_mode="target", target_leverage=5)
    pv = public.preview_wallet(LEADER1, req, Settings(), venue=venue, now_ms=9)
    assert pv.copied == 4 and pv.skipped == 11
    assert pv.planned_margin_usd == pytest.approx(20.0)
    assert pv.min_allocation_for_full_book == pytest.approx(420.0)
    c01 = pv.slices[0]
    assert c01.coin == "C01" and c01.fill_cycles == 3 and pv.multi_cycle


def test_preview_raises_when_his_read_fails(data_dir, venue):
    from engine import public

    from contracts.models import WalletCopyRequest
    venue.fail_account(LEADER1)
    with pytest.raises(public.PreviewUnavailable):
        public.preview_wallet(LEADER1, WalletCopyRequest(allocation_usd=10.0), Settings(),
                              venue=venue)
