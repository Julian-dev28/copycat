from __future__ import annotations

import pytest
from discovery.positions import coins_traded, median_hold_hours, merged_timeline, opens_per_day, reconstruct


def fill(time_ms, coin, px, sz, side, start_position, fee=0.0, closed_pnl=0.0):
    return {"time_ms": time_ms, "coin": coin, "px": px, "sz": sz, "side": side,
            "start_position": start_position, "fee": fee, "closed_pnl": closed_pnl}


def test_open_add_reduce_and_flip_splits_into_close_plus_open():
    fills = [
        fill(1000, "BTC", 100.0, 1.0, "B", 0.0),     # open long 0 -> 1.0
        fill(2000, "BTC", 110.0, 0.5, "B", 1.0),     # add 1.0 -> 1.5
        fill(3000, "BTC", 120.0, 0.5, "A", 1.5),     # reduce 1.5 -> 1.0
        fill(4000, "BTC", 90.0, 2.0, "A", 1.0),      # flip: sell 2.0, 1.0 -> -1.0
        fill(5000, "BTC", 95.0, 1.0, "B", -1.0),     # close short -1.0 -> 0
    ]
    by_coin = reconstruct(fills)
    events = by_coin["BTC"]
    kinds = [(e.kind, e.side, e.start_position, e.end_position) for e in events]
    assert kinds == [
        ("open", "long", 0.0, 1.0),
        ("add", "long", 1.0, 1.5),
        ("reduce", "long", 1.5, 1.0),
        ("close", "long", 1.0, 0.0),     # flip's close half
        ("open", "short", 0.0, -1.0),    # flip's open half
        ("close", "short", -1.0, 0.0),
    ]
    # the flip's two synthetic events keep the leader's real fill price/time
    assert events[3].time_ms == 4000 and events[3].px == 90.0
    assert events[4].time_ms == 4000 and events[4].px == 90.0


def test_zero_to_zero_fill_produces_no_event():
    fills = [fill(1000, "BTC", 100.0, 0.0, "B", 0.0)]
    by_coin = reconstruct(fills)
    assert by_coin == {}


def test_merged_timeline_interleaves_coins_chronologically():
    fills = [
        fill(1000, "BTC", 100.0, 1.0, "B", 0.0),
        fill(500, "ETH", 50.0, 1.0, "B", 0.0),
        fill(1500, "ETH", 55.0, 1.0, "A", 1.0),
    ]
    by_coin = reconstruct(fills)
    timeline = merged_timeline(by_coin)
    assert [(e.coin, e.time_ms) for e in timeline] == [("ETH", 500), ("BTC", 1000), ("ETH", 1500)]


def test_opens_per_day_counts_every_open_including_still_open_positions():
    fills = [
        fill(0, "BTC", 100.0, 1.0, "B", 0.0),               # opens, closes within window
        fill(3_600_000, "BTC", 110.0, 1.0, "A", 1.0),
        fill(0, "ETH", 50.0, 1.0, "B", 0.0),                 # opens, never closes
    ]
    by_coin = reconstruct(fills)
    assert opens_per_day(by_coin, window_days=1) == pytest.approx(2.0)
    assert coins_traded(by_coin) == ["BTC", "ETH"]


def test_median_hold_hours_excludes_incomplete_trips():
    fills = [
        fill(0, "BTC", 100.0, 1.0, "B", 0.0),
        fill(3_600_000, "BTC", 110.0, 1.0, "A", 1.0),   # complete 1h trip
        fill(0, "ETH", 50.0, 1.0, "B", 0.0),             # never closes: excluded
    ]
    by_coin = reconstruct(fills)
    median, n = median_hold_hours(by_coin)
    assert n == 1
    assert median == pytest.approx(1.0)


def test_median_hold_hours_none_when_no_complete_trips():
    fills = [fill(0, "BTC", 100.0, 1.0, "B", 0.0)]
    by_coin = reconstruct(fills)
    median, n = median_hold_hours(by_coin)
    assert median is None
    assert n == 0


from discovery.positions import (  # noqa: E402
    coalesce_by_poll,
    final_positions,
    is_perp_coin,
    split_perp,
    trip_spans,
)


def test_perp_filter_drops_spot_and_outcome_ids():
    """Regression (coordinator bug 1): '#12100' / '@151' reached candleSnapshot and 500'd."""
    assert is_perp_coin("BTC") and is_perp_coin("xyz:DRAM") and is_perp_coin("kPEPE")
    assert not is_perp_coin("@151") and not is_perp_coin("#12100") and not is_perp_coin("PURR/USDC")
    perp, other = split_perp([fill(1, "BTC", 1, 1, "B", 0), fill(2, "#12100", 1, 1, "B", 0)])
    assert [f["coin"] for f in perp] == ["BTC"] and [f["coin"] for f in other] == ["#12100"]


def test_coalesce_merges_fills_inside_one_poll_into_one_net_delta():
    fills = [fill(1_000, "BTC", 100.0, 1.0, "B", 0.0),
             fill(2_000, "BTC", 102.0, 1.0, "B", 1.0),
             fill(4_000, "BTC", 101.0, 0.5, "A", 2.0),
             fill(6_000, "BTC", 99.0, 1.0, "A", 1.5)]
    out = coalesce_by_poll(fills, 5_000)
    assert len(out) == 2
    first = out[0]
    assert first["start_position"] == 0.0 and first["side"] == "B" and first["sz"] == pytest.approx(1.5)
    assert first["px"] == pytest.approx((100 + 102 + 0.5 * 101) / 2.5)
    events = reconstruct(out)["BTC"]
    assert [(e.kind, e.start_position, e.end_position) for e in events] == [("open", 0.0, 1.5), ("reduce", 1.5, 0.5)]


def test_coalesce_open_and_close_inside_one_poll_is_invisible():
    fills = [fill(1_000, "ETH", 10.0, 1.0, "B", 0.0), fill(2_000, "ETH", 11.0, 1.0, "A", 1.0)]
    assert reconstruct(coalesce_by_poll(fills, 5_000)) == {}


def test_coalesce_same_ms_ties_use_the_chain_start():
    fills = [fill(1_000, "BTC", 100.0, 1.0, "B", 1.0), fill(1_000, "BTC", 100.0, 1.0, "B", 0.0)]
    out = coalesce_by_poll(fills, 5_000)
    assert out[0]["start_position"] == 0.0 and out[0]["sz"] == 2.0


def test_final_positions_and_trip_spans():
    fills = [fill(0, "BTC", 100.0, 1.0, "B", 0.0), fill(10, "BTC", 100.0, 1.0, "A", 1.0),
             fill(20, "ETH", 10.0, 2.0, "A", 0.0)]
    assert final_positions(fills) == {"BTC": 0.0, "ETH": -2.0}
    assert trip_spans(reconstruct(fills), 99) == {"BTC": [(0, 10)], "ETH": [(20, 99)]}
