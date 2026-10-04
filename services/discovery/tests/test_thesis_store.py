"""Store round trip, TTL reuse, the public surface on a fake venue (fills
and candles through the shared caches), and candles_public."""
from __future__ import annotations

import os

import pytest
from discovery import candles_public
from discovery.thesis import public, store
from test_thesis_fixtures import ADDR, T0, D, H, ThesisVenue, candle_rows, portfolio, trip_fills

from contracts.models import Thesis

NOW = T0 + 20 * D
CLOSES = [100 * (1.001 ** i) for i in range(24 * 21)]


@pytest.fixture(autouse=True)
def _restore_hl_priority(monkeypatch):
    """public.* switches this process to the background HL priority; undo it
    so other suites keep the engine class."""
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", os.environ.get("COPYCAT_HL_PRIORITY", "engine"))
    try:
        from hl import rate_limit
        before = getattr(rate_limit.HL_LIMITER, "priority", "engine")
    except (ImportError, AttributeError):
        rate_limit, before = None, None
    yield
    if rate_limit is not None and getattr(rate_limit.HL_LIMITER, "priority", None) != before:
        rate_limit.set_priority(before)


def venue_with_book() -> ThesisVenue:
    v = ThesisVenue()
    fills = []
    for k in range(6):
        o = T0 + (250 + k * 30) * H
        fills += trip_fills("BTC", "long", o, CLOSES[(o - T0) // H - 1], o + 5 * H, CLOSES[(o - T0) // H + 4])
    v.set_fills(ADDR, fills)
    v.set_candles("BTC", "1h", candle_rows(CLOSES))
    v.set_portfolio(ADDR, portfolio([(T0, 10_000.0)]))
    return v


def test_save_and_get_theses_latest_per_source(conn):
    a = Thesis(address=ADDR.upper().replace("0X", "0x"), source="claude_code", created_ms=1, title="v1",
               markdown="old")
    public.save_thesis(a, conn=conn)
    public.save_thesis(a.model_copy(update={"created_ms": 5, "title": "v2", "markdown": "new"}), conn=conn)
    public.save_thesis(Thesis(address=ADDR, source="ta", created_ms=3, title="ta", markdown="x"), conn=conn)
    got = public.get_theses(ADDR, conn=conn)
    assert [(t.source, t.title) for t in got] == [("claude_code", "v2"), ("ta", "ta")]
    assert got[0].address == ADDR
    assert public.get_theses("0x" + "cd" * 20, conn=conn) == []


def test_bad_address_rejected(conn):
    with pytest.raises(ValueError):
        public.get_theses("not-an-address", conn=conn)


def test_fingerprint_reads_through_caches_and_honours_ttl(conn):
    v = venue_with_book()
    fp = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW)
    assert fp.trips_analyzed == 6 and fp.trend_aligned_pct == 100.0
    assert fp.avg_leverage is not None and os.environ["COPYCAT_HL_PRIORITY"] == "background"
    calls = (len(v.fills_calls), len(v.candles_calls), v.portfolio_calls)
    again = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW + 60_000)       # inside the 1h TTL
    assert again == fp and (len(v.fills_calls), len(v.candles_calls), v.portfolio_calls) == calls
    later = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW + 2 * H)         # past the TTL
    assert later.as_of_ms == NOW + 2 * H and v.portfolio_calls == calls[2] + 1
    public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW + 2 * H, refresh=True)
    assert v.portfolio_calls == calls[2] + 2


def test_store_ttl_reader(conn):
    store.ensure_schema(conn)
    fp = public.fingerprint(ADDR, 30, venue_with_book(), conn=conn, now_ms=NOW)
    assert store.get_fingerprint(conn, ADDR, 30, NOW + 10_000, 60) == fp
    assert store.get_fingerprint(conn, ADDR, 30, NOW + 61_000, 60) is None
    assert store.get_fingerprint(conn, ADDR, 30, NOW + 10 ** 9, -1) == fp
    assert store.get_fingerprint(conn, ADDR, 7, NOW, 60) is None


def test_ta_thesis_uses_given_fingerprint_without_reads(conn):
    v = venue_with_book()
    fp = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW)
    n = len(v.fills_calls)
    t = public.ta_thesis(ADDR, fingerprint=fp, conn=conn)
    assert len(v.fills_calls) == n
    assert t.source == "ta" and t.fingerprint_as_of_ms == NOW and t.title.startswith("TA fingerprint: ")
    assert "## Evidence" in t.markdown and fp.summary in t.markdown
    assert [x.source for x in public.get_theses(ADDR, conn=conn)] == ["ta"]
    t2 = public.ta_thesis(ADDR, conn=conn, now_ms=NOW + 1000)       # stored fingerprint, inside TTL
    assert t2.markdown == t.markdown and len(v.fills_calls) == n


def test_fills_failure_is_an_error_not_a_flat_trader(conn):
    v = venue_with_book()
    v.fail_fills.add(ADDR)
    with pytest.raises(public.ThesisError):
        public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW)


def test_candle_failure_becomes_a_caveat(conn):
    v = venue_with_book()
    v.fail_candles.add("BTC")
    fp = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW)
    assert fp.trend_aligned_pct is None
    assert any("candle read failed for BTC" in c for c in fp.caveats)
    assert any("No usable 1h candles for 6 of 6" in c for c in fp.caveats)


def test_equity_falls_back_to_account_state(conn):
    v = venue_with_book()
    v.set_portfolio(ADDR, None)
    v.set_account_state(ADDR, {"equity_perp_usd": 2000.0, "spot_usdc": 0.0})
    fp = public.fingerprint(ADDR, 30, v, conn=conn, now_ms=NOW)
    assert fp.avg_leverage is not None
    assert any("today's account value" in c for c in fp.caveats)


def test_candles_public_reads_through_the_cache(conn):
    v = ThesisVenue()
    v.set_candles("ETH", "1h", candle_rows([10.0, 11.0, 12.0, 13.0]))
    rows = candles_public.candles("ETH", "1h", T0, T0 + 3 * H, venue=v, conn=conn, now_ms=T0 + 10 * H)
    assert [r["c"] for r in rows] == [10.0, 11.0, 12.0, 13.0] and set(rows[0]) == {"t_ms", "o", "h", "l", "c", "v"}
    n = len(v.candles_calls)
    candles_public.candles("ETH", "1h", T0, T0 + 3 * H, venue=v, conn=conn, now_ms=T0 + 10 * H)
    assert len(v.candles_calls) == n                                   # served from coverage
    candles_public.candles("ETH", "1h", 0, T0 + 3 * H, venue=v, conn=conn, now_ms=T0 + 10 * H)
    assert v.candles_calls[-1][2] >= T0 + 3 * H - 4999 * H              # clamped to 5000 bars
    with pytest.raises(ValueError):
        candles_public.candles("ETH", "7m", T0, T0 + H, venue=v, conn=conn)
