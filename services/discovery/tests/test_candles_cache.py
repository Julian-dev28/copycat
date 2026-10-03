from __future__ import annotations

from discovery import candles_cache

from discovery_fakes import FakeVenue, flat_candles


def test_get_candles_fetches_once_then_serves_from_cache(conn):
    venue = FakeVenue()
    venue.set_candles("BTC", "1m", flat_candles(0, 300_000, 100.0))

    rows1 = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 180_000)
    assert len(rows1) == 4  # 0,60000,120000,180000
    assert venue.candles_calls == [("BTC", "1m", 0, 180_000)]

    rows_again = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 180_000)
    assert len(rows_again) == 4
    assert len(venue.candles_calls) == 1  # fully cached: no second fetch

    rows2 = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 300_000)
    assert len(rows2) == 6  # 0..300000 inclusive every 60000
    assert len(venue.candles_calls) == 2
    assert venue.candles_calls[1] == ("BTC", "1m", 240_000, 300_000)  # only the new gap


def test_get_candles_different_coins_cached_independently(conn):
    venue = FakeVenue()
    venue.set_candles("BTC", "1m", flat_candles(0, 60_000, 100.0))
    venue.set_candles("ETH", "1m", flat_candles(0, 60_000, 50.0))

    btc = candles_cache.get_candles(conn, venue, "BTC", "1m", 0, 60_000)
    eth = candles_cache.get_candles(conn, venue, "ETH", "1m", 0, 60_000)
    assert [r["o"] for r in btc] == [100.0, 100.0]
    assert [r["o"] for r in eth] == [50.0, 50.0]
