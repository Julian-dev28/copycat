"""Coattail-rider detector (user_consensus_2026-10 P1 #6): pure, no I/O."""
from __future__ import annotations

from discovery.scout import coattail as CT

M = 60_000
S = 1_000


def op(addr, coin, side, t_ms):
    return CT.Open(address=addr, coin=coin, side=side, t_ms=t_ms)


def test_opens_from_fills_reads_only_open_dir():
    fills = [
        {"dir": "Open Long", "coin": "BTC", "time_ms": 1_000},
        {"dir": "Open Short", "coin": "ETH", "time_ms": 2_000},
        {"dir": "Close Long", "coin": "BTC", "time_ms": 3_000},
        {"dir": "Liquidated Isolated Long", "coin": "BTC", "time_ms": 4_000},
    ]
    out = CT.opens_from_fills("0xa", fills)
    assert out == [op("0xa", "BTC", "long", 1_000), op("0xa", "ETH", "short", 2_000)]


def test_consistent_follower_flagged_leader_is_not():
    """0xfollower opens BTC long 30s after 0xleader every time, 6 times:
    share 100% >= MIN_SHARE, count 6 >= MIN_OPENS -> flagged. The leader
    itself has no earlier wallet to lag, so it is never flagged."""
    opens = []
    for i in range(6):
        t = i * 10 * M
        opens.append(op("0xleader", "BTC", "long", t))
        opens.append(op("0xfollower", "BTC", "long", t + 30 * S))
    out = CT.detect_coattails(opens)
    assert "0xfollower" in out
    leader, share, count = out["0xfollower"]
    assert leader == "0xleader" and share == 1.0 and count == 6
    assert "0xleader" not in out


def test_near_simultaneous_fills_not_counted_as_lag():
    """Same-millisecond-ish fills (under LAG_MIN_MS) are not a "lag": two
    wallets reacting to the exact same event aren't a coattail pattern."""
    opens = []
    for i in range(6):
        t = i * 10 * M
        opens.append(op("0xa", "BTC", "long", t))
        opens.append(op("0xb", "BTC", "long", t + 200))     # 200ms < LAG_MIN_MS (1000ms)
    out = CT.detect_coattails(opens)
    assert out == {}


def test_lag_past_max_window_not_counted():
    opens = []
    for i in range(6):
        t = i * 10 * M
        opens.append(op("0xa", "BTC", "long", t))
        opens.append(op("0xb", "BTC", "long", t + CT.LAG_MAX_MS + 5_000))   # just past the window
    out = CT.detect_coattails(opens)
    assert out == {}


def test_below_min_opens_not_flagged():
    opens = []
    for i in range(CT.MIN_OPENS - 1):
        t = i * 10 * M
        opens.append(op("0xa", "BTC", "long", t))
        opens.append(op("0xb", "BTC", "long", t + 30 * S))
    assert CT.detect_coattails(opens) == {}


def test_below_min_share_not_flagged():
    """Half the time 0xb lags 0xa, half the time it opens on its own
    (nothing precedes it within the window): share 50% < MIN_SHARE (50% is
    the boundary and MIN_SHARE itself passes, so push it to 40%: 4 of 10)."""
    opens = []
    for i in range(4):
        t = i * 10 * M
        opens.append(op("0xa", "BTC", "long", t))
        opens.append(op("0xb", "BTC", "long", t + 30 * S))
    for i in range(6):
        opens.append(op("0xb", "ETH", "short", (100 + i) * 10 * M))   # independent coin, no leader
    out = CT.detect_coattails(opens)
    assert "0xb" not in out


def test_different_coin_or_side_never_matched():
    """0xb has enough opens to clear MIN_OPENS, each one 30s after an 0xa
    open, but every pair differs by coin or by side -> never the same
    (coin, side) bucket, so no match is ever recorded."""
    opens = []
    for i in range(6):
        t = i * 10 * M
        opens.append(op("0xa", "BTC", "long", t))
        if i % 2 == 0:
            opens.append(op("0xb", "BTC", "short", t + 30 * S))     # same coin, different side
        else:
            opens.append(op("0xb", "ETH", "long", t + 30 * S))     # different coin, same side
    assert CT.detect_coattails(opens) == {}


def test_deterministic():
    opens = []
    for i in range(8):
        t = i * 10 * M
        opens.append(op("0xleader", "BTC", "long", t))
        opens.append(op("0xfollower", "BTC", "long", t + 30 * S))
    assert CT.detect_coattails(opens) == CT.detect_coattails(list(reversed(opens)))
