"""Live eval (not the gate): checks `engine.sizing.account_equity`'s
unified-account formula against Hyperliquid's own portfolio value.

    .venv/bin/python -m pytest services/engine/tests/test_live_equity.py -m live -v

Picks the first wallet that is in unified mode and holds only USDC on spot
(other spot tokens are valued by HL's portfolio but are not part of the
copy engine's equity), then asserts spot USDC + uPnL is within 3% of HL's
portfolio accountValue while perp accountValue + spot USDC is far off.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

CANDIDATES = [
    "0xac142fee46f8dacbfef23e1e41d79f1f7233487e",
    "0x95da8596c44dd09f4b8becce87ad3b7894fb2328",
    "0xe2823659be02e0f48a4660e4da008b5e1abfdf29",
]


def _info(body):
    from hl.http import http_post
    return http_post("/info", body)


def test_unified_equity_matches_hl_portfolio_value():
    from engine import sizing
    from hl import HlVenue

    for user in CANDIDATES:
        if _info({"type": "userAbstraction", "user": user}) != "unifiedAccount":
            continue
        spot = _info({"type": "spotClearinghouseState", "user": user}) or {}
        # dust (< $10 at cost) does not move a 3% comparison; anything bigger would
        others = [b for b in spot.get("balances", []) if b["coin"] != "USDC"
                  and float(b["total"]) > 0 and (float(b.get("entryNtl") or 0) >= 10
                                                 or float(b.get("entryNtl") or 0) == 0)]
        if others:
            continue
        acct = HlVenue().account_state(user)
        assert acct is not None
        portfolio = dict(_info({"type": "portfolio", "user": user}))
        hl_value = float(portfolio["day"]["accountValueHistory"][-1][1])
        unified = sizing.account_equity({**acct, "abstraction": "unifiedAccount"})
        naive = sizing.account_equity(acct)
        print(f"\n[live] {user}: HL={hl_value:.0f} unified={unified:.0f} naive={naive:.0f}")
        assert abs(unified - hl_value) / hl_value < 0.03
        assert abs(naive - hl_value) / hl_value > 0.30
        return
    pytest.skip("no USDC-only unified wallet among the candidates today")
