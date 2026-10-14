"""ScoutSimTerms (contract v16): the Scout board's own copy-sim terms, apart
from the operator's live trading Settings.

    - the model: field defaults (the new reference), validation (mirrors
      LeaderOverride), to_settings() (sizing_mode always allocation, leverage
      doubles as the book-wide cap).
    - store: sim_terms()/set_sim_terms() (plain scout_meta blob),
      simmed_addresses() (which wallets' candles are already cached).
    - refresh: terms_hash/effective_hash/effective_sim_equity/
      effective_settings_for_leader (pure), and the live pipeline: a terms
      change re-sims from cache (zero new HL/candle reads), switching back to
      an earlier terms sheet is instant (0 sims), use_live_settings=True is
      byte-identical to the pre-v16 board.
    - public: scout_sim_terms_get/set (GET/PUT's backing functions).
"""
from __future__ import annotations

import pytest
from discovery.scout import public, simstage, stats, store
from discovery.scout import refresh as R
from engine import sizing as real_sizing
from test_scout_helpers import addr, flat_15m, portfolio, trips
from test_scout_world import BOARD, DAY, EQUITY, NOW, G, q, settings, world

from contracts.models import (
    HL_MIN_ORDER_USD,
    MAX_LEVERAGE_CAP,
    ExposureMode,
    LeverageMode,
    MarginMode,
    ScoutSimTerms,
    Settings,
    SizingMode,
    SmallAccountMode,
)


@pytest.fixture
def w(tmp_path, monkeypatch):
    return world(tmp_path, monkeypatch)


# ── the model ────────────────────────────────────────────────────────────────

def test_defaults_are_the_documented_reference():
    """Measured on a 40-wallet real-HL throwaway stack (scout/README.md "Sim
    terms"): exposure_mode=target fixed at 3x beat every exposure_mode=match
    cap tried (0 sim liquidations vs 4-10, Fit<=20 on 15/40 wallets vs 35-40/40),
    so the default is NOT the spec's first candidate (match, capped 10x)."""
    t = ScoutSimTerms()
    assert t.use_live_settings is False
    assert (t.sim_equity_usd, t.allocation_usd) == (1_000.0, 100.0)
    assert (t.exposure_mode, t.leverage_mode, t.target_leverage, t.leverage) == (
        ExposureMode.target, LeverageMode.fixed, 3, 3)
    assert (t.margin_mode, t.max_worse_entry_pct, t.small_account_mode) == (
        MarginMode.isolated, 10.0, SmallAccountMode.concentrate)


@pytest.mark.parametrize("field,bad", [
    ("sim_equity_usd", 0), ("sim_equity_usd", -5),
    ("allocation_usd", HL_MIN_ORDER_USD - 0.01),
    ("leverage", 0), ("leverage", MAX_LEVERAGE_CAP + 1),
    ("target_leverage", 0), ("target_leverage", MAX_LEVERAGE_CAP + 1),
    ("max_worse_entry_pct", -1), ("max_worse_entry_pct", 100.01),
])
def test_validation_mirrors_leader_override_ranges(field, bad):
    with pytest.raises(ValueError):
        ScoutSimTerms(**{field: bad})


def test_unknown_fields_are_ignored_like_leader_override():
    ScoutSimTerms.model_validate({"allocation_usd": 50, "not_a_field": 1})  # extra="ignore": no raise


def test_to_settings_sizing_mode_and_leverage_cap():
    t = ScoutSimTerms(allocation_usd=250.0, exposure_mode=ExposureMode.target, target_leverage=7,
                      leverage_mode=LeverageMode.fixed, leverage=12, margin_mode=MarginMode.cross,
                      max_worse_entry_pct=4.0, small_account_mode=SmallAccountMode.bump)
    s = t.to_settings()
    assert isinstance(s, Settings)
    assert s.sizing_mode == SizingMode.allocation
    assert (s.allocation_usd, s.exposure_mode, s.target_leverage) == (250.0, ExposureMode.target, 7)
    assert (s.leverage_mode, s.leverage) == (LeverageMode.fixed, 12)
    # leverage is ALSO the book-wide cap, whatever leverage_mode says (models.py docstring)
    assert s.max_position_leverage == 12
    assert (s.margin_mode, s.max_worse_entry_pct, s.small_account_mode) == (
        MarginMode.cross, 4.0, SmallAccountMode.bump)
    # everything else is the plain Settings() default, not the operator's own book
    d = Settings()
    assert (s.poll_interval_s, s.max_open_copies, s.trade_direction) == (
        d.poll_interval_s, d.max_open_copies, d.trade_direction)
    assert s.leaders == [] and s.enabled is False


def test_to_settings_match_mode_cap_follows_leverage_field():
    """'follow their leverage, capped at Nx': leverage_mode=match, leverage=N
    means the cap IS N, not Settings()'s own 50."""
    s = ScoutSimTerms(exposure_mode=ExposureMode.match, leverage_mode=LeverageMode.match, leverage=10).to_settings()
    assert s.leverage_mode == LeverageMode.match and s.max_position_leverage == 10


def test_to_settings_default_is_fixed_low_leverage_target():
    """The default (measured, see test_defaults_are_the_documented_reference):
    exposure_mode=target, fixed 3x, which is ALSO the book-wide cap."""
    s = ScoutSimTerms().to_settings()
    assert s.exposure_mode == ExposureMode.target and s.leverage_mode == LeverageMode.fixed
    assert (s.target_leverage, s.leverage, s.max_position_leverage) == (3, 3, 3)


# ── store ────────────────────────────────────────────────────────────────────

def test_store_sim_terms_round_trip(tmp_path):
    conn = store.connect(tmp_path / "s.db")
    assert store.sim_terms(conn) is None
    store.set_sim_terms(conn, ScoutSimTerms(allocation_usd=333.0).model_dump(mode="json"))
    got = store.sim_terms(conn)
    assert got["allocation_usd"] == 333.0
    assert ScoutSimTerms.model_validate(got).allocation_usd == 333.0


def test_store_simmed_addresses(tmp_path):
    conn = store.connect(tmp_path / "s.db")
    assert store.simmed_addresses(conn, []) == set()
    assert store.simmed_addresses(conn, ["0xnew"]) == set()
    store.save_sim(conn, "0xold", "hash1", 1000.0, 1, 1, {"score": 1.0}, [])
    assert store.simmed_addresses(conn, ["0xold", "0xnew"]) == {"0xold"}
    # any hash counts, not just the one being asked about
    assert store.simmed_addresses(conn, ["0xold"]) == {"0xold"}


# ── refresh: pure hash/dispatch functions ────────────────────────────────────

def test_terms_hash_ignores_use_live_settings_but_not_other_fields():
    live_true = R.terms_hash(ScoutSimTerms(use_live_settings=True))
    live_false = R.terms_hash(ScoutSimTerms(use_live_settings=False))
    assert live_true == live_false            # only the flag differs: same hash
    assert R.terms_hash(ScoutSimTerms(allocation_usd=200.0)) != live_false


def test_effective_hash_dispatches_to_settings_hash_or_terms_hash():
    s = settings()
    assert R.effective_hash(ScoutSimTerms(use_live_settings=True), s, EQUITY) == R.settings_hash(s, EQUITY)
    custom = ScoutSimTerms(use_live_settings=False, allocation_usd=150.0)
    assert R.effective_hash(custom, s, EQUITY) == R.terms_hash(custom)
    # the two hash spaces never collide by construction
    assert R.effective_hash(custom, s, EQUITY) != R.settings_hash(s, EQUITY)


def test_effective_sim_equity_dispatches():
    assert R.effective_sim_equity(ScoutSimTerms(use_live_settings=True), 777.0) == 777.0
    assert R.effective_sim_equity(ScoutSimTerms(use_live_settings=False, sim_equity_usd=42.0), 777.0) == 42.0


def test_effective_settings_for_leader_dispatches():
    s = settings()                                           # leaders=[G], fixed_margin sizing
    live = R.effective_settings_for_leader(ScoutSimTerms(use_live_settings=True), s)
    assert live(G).sizing_mode == s.for_leader(G).sizing_mode == SizingMode.fixed_margin
    terms = ScoutSimTerms(use_live_settings=False, allocation_usd=99.0)
    custom = R.effective_settings_for_leader(terms, s)
    assert custom(G).sizing_mode == SizingMode.allocation and custom(G).allocation_usd == 99.0
    assert custom(G) == custom("0xanyone-else")                # one sheet for the whole board, no per-leader


# ── public: GET/PUT backing functions ────────────────────────────────────────

def test_public_sim_terms_default_then_set(w):
    public.configure(db_path=w["db"], venue=w["venue"])
    default = public.scout_sim_terms_get()
    assert default == ScoutSimTerms()
    saved = public.scout_sim_terms_set(ScoutSimTerms(allocation_usd=444.0))
    assert saved.allocation_usd == 444.0
    assert public.scout_sim_terms_get().allocation_usd == 444.0


# ── live pipeline: terms change, cache-only re-sim, instant switch back ──────

def test_terms_change_is_stale_then_cache_only_resim_publishes(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    old = public.scout_page(q())
    assert old.settings_hash == R.settings_hash(settings(), EQUITY)   # world() used use_live_settings
    new_terms = ScoutSimTerms(use_live_settings=False, allocation_usd=250.0, sim_equity_usd=2_000.0)
    # what tick() writes at once, before it runs any stage: the board is stale right away
    store.meta_set(conn, {"wanted_hash": R.terms_hash(new_terms)})
    stale = public.scout_page(q())
    assert stale.stale_settings and stale.settings_hash == old.settings_hash
    v.candles_calls.clear()
    R.tick(v, settings(), EQUITY, db_path=db, terms=new_terms)
    after = public.scout_page(q())
    assert not after.stale_settings and after.settings_hash == R.terms_hash(new_terms)
    assert v.candles_calls == []                                      # cache-only: zero candle reads
    assert after.sim_equity_usd == new_terms.sim_equity_usd
    assert after.rows[0].score.sim_return_pct != old.rows[0].score.sim_return_pct


def test_switch_back_to_earlier_terms_is_instant(w):
    v, db = w["venue"], w["db"]
    new_terms = ScoutSimTerms(use_live_settings=False, allocation_usd=250.0)
    R.run_refresh(v, settings(), EQUITY, R.RefreshOptions(stages=("C",), kind="settings changed"),
                 db_path=db, terms=new_terms)
    live_terms = ScoutSimTerms(use_live_settings=True)
    v.candles_calls.clear()
    rep = R.run_refresh(v, settings(), EQUITY, R.RefreshOptions(stages=("C",), kind="settings changed"),
                        db_path=db, terms=live_terms)
    assert rep.sims_done == 0 and rep.published                       # every wallet already simmed at this hash
    assert v.candles_calls == []
    assert public.scout_page(q()).settings_hash == R.settings_hash(settings(), EQUITY)


def test_use_live_settings_true_never_goes_cache_only_even_for_already_simmed_wallets(w, monkeypatch):
    """A genuine live-Settings change (not a sim-terms change) must behave exactly
    as before v16: every wallet sims on the real venue, never CacheOnlyVenue, even
    though world()'s first build already simmed (and cached candles for) all of
    them. allow_cache_only must be False whenever terms.use_live_settings is True."""
    v, db = w["venue"], w["db"]
    built = []
    real_init = simstage.CacheOnlyVenue.__init__

    def spy_init(self):
        built.append(True)
        real_init(self)

    monkeypatch.setattr(simstage.CacheOnlyVenue, "__init__", spy_init)
    new_settings = settings(fixed_margin_usd=2.0)      # a real Settings change, every wallet already simmed
    rep = R.run_refresh(v, new_settings, EQUITY, R.RefreshOptions(stages=("C",), kind="settings changed"),
                        db_path=db, terms=ScoutSimTerms(use_live_settings=True))
    assert rep.sims_done == len(BOARD)
    assert built == []                                  # CacheOnlyVenue never constructed


def test_terms_change_does_go_cache_only_for_already_simmed_wallets(w, monkeypatch):
    """Mirror of the test above, proving the two paths really differ: the SAME
    already-simmed board, but a sim-terms (not use_live_settings) change DOES use
    CacheOnlyVenue for every wallet."""
    v, db = w["venue"], w["db"]
    built = []
    real_init = simstage.CacheOnlyVenue.__init__

    def spy_init(self):
        built.append(True)
        real_init(self)

    monkeypatch.setattr(simstage.CacheOnlyVenue, "__init__", spy_init)
    new_terms = ScoutSimTerms(use_live_settings=False, allocation_usd=321.0)
    rep = R.run_refresh(v, settings(), EQUITY, R.RefreshOptions(stages=("C",), kind="settings changed"),
                        db_path=db, terms=new_terms)
    assert rep.sims_done == len(BOARD)
    assert len(built) == len(BOARD)                      # one CacheOnlyVenue per wallet, all already simmed


def test_run_stage_c_real_venue_for_a_never_simmed_wallet_even_with_allow_cache_only(w):
    """A brand new wallet (never simmed under ANY hash) always gets the real
    venue, whatever allow_cache_only says: store.simmed_addresses excludes it."""
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    h = addr(9)
    # a coin none of world()'s 6 wallets ever traded: its candles are NOT on disk yet,
    # so only a real venue call can serve them (BTC/ETH/xyz:TSLA/SOL are already fully
    # cached from world()'s own first build and would pass with cache_only by accident).
    v.set_candles("DOGE", "15m", flat_15m(1.0, NOW - 10 * DAY, NOW))
    v.set_portfolio(h, portfolio([0, 5, 10, 15] * 13, av=20_000.0))
    v.set_fills(h, trips("DOGE", 4, NOW - 9 * DAY))
    v.set_account_state(h, {"equity_perp_usd": 20_000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})
    stats.run_stage_b(conn, v, [h], R.now_ms(), stats.Budget(1e9, 60), book=[], requested=[h])
    assert store.simmed_addresses(conn, [h]) == set()     # confirms the premise
    v.candles_calls.clear()
    terms = ScoutSimTerms(allocation_usd=111.0)
    res = simstage.run_stage_c(conn, v, [h], R.effective_settings_for_leader(terms, settings()),
                               terms.sim_equity_usd, R.terms_hash(terms), stats.Budget(1e9, 60),
                               real_sizing, allow_cache_only=True)
    assert res.done == [h]
    assert v.candles_calls != []                           # a real fetch happened for the new wallet
