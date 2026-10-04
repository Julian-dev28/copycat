from __future__ import annotations

from discovery.leaderboard import pull_candidates
from discovery_fakes import FakeVenue


def row(address, account_value, pnl_30d, pnl_all_time, vlm_30d, is_vault=False, display=None):
    return {
        "ethAddress": address,
        "accountValue": str(account_value),
        "displayName": display,
        "isVault": is_vault,
        "windowPerformances": [
            ["day", {"pnl": "1", "roi": "0.01", "vlm": "100"}],
            ["week", {"pnl": "1", "roi": "0.01", "vlm": "100"}],
            ["month", {"pnl": str(pnl_30d), "roi": "0.1", "vlm": str(vlm_30d)}],
            ["allTime", {"pnl": str(pnl_all_time), "roi": "1.0", "vlm": str(vlm_30d * 10)}],
        ],
    }


def test_filters_by_account_value_volume_and_positive_pnl():
    venue = FakeVenue()
    venue.set_leaderboard([
        row("0xA", 100_000, 5_000, 20_000, 60_000),         # passes everything
        row("0xB", 5_000, 5_000, 20_000, 60_000),            # fails account value floor
        row("0xC", 100_000, 5_000, 20_000, 10_000),          # fails volume floor
        row("0xD", 100_000, -1, 20_000, 60_000),             # negative 30d pnl
        row("0xE", 100_000, 5_000, -1, 60_000),              # negative all-time pnl
    ])
    out = pull_candidates(venue, min_account_value_usd=10_000, min_volume_30d_usd=50_000, top_n=50)
    assert [c.address for c in out] == ["0xa"]


def test_ranks_by_30d_pnl_descending_and_respects_top_n():
    venue = FakeVenue()
    venue.set_leaderboard([
        row("0xA", 100_000, 1_000, 5_000, 60_000),
        row("0xB", 100_000, 9_000, 5_000, 60_000),
        row("0xC", 100_000, 5_000, 5_000, 60_000),
    ])
    out = pull_candidates(venue, min_account_value_usd=10_000, min_volume_30d_usd=50_000, top_n=2)
    assert [c.address for c in out] == ["0xb", "0xc"]


def test_vault_flagged_not_dropped():
    venue = FakeVenue()
    venue.set_leaderboard([row("0xA", 100_000, 5_000, 20_000, 60_000, is_vault=True)])
    out = pull_candidates(venue, min_account_value_usd=10_000, min_volume_30d_usd=50_000, top_n=50)
    assert len(out) == 1
    assert "vault" in out[0].flags


def test_empty_leaderboard_returns_empty_list():
    venue = FakeVenue()
    venue.set_leaderboard(None)
    assert pull_candidates(venue, 0, 0, 50) == []
    venue.set_leaderboard([])
    assert pull_candidates(venue, 0, 0, 50) == []
