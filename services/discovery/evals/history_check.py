"""Live check of trade history correctness (contract v17, user_consensus
Trade history correctness checklist) against a THROWAWAY copycat stack
(history_check.sh starts it: temp data dir, no account, no agent key,
trading off) that reads REAL Hyperliquid data.

For each wallet: polls its on-demand trader file (GET /api/scout/traders/
{address}) until ready, then takes the SERVED `recent_trips` at face value
(it is capped at 100, newest first -- a hyperactive wallet's served trips
can span a much shorter range than the full 30d window, so every ground-
truth comparison below is scoped to exactly [min(opened_ms), max(closed_ms)]
of what was actually served, never the full window). Ground truth for that
same span comes from a DIRECT Hyperliquid read (contracts.venue via
hl.venue.HlVenue), bypassing the fills cache entirely, so a caching or
serialization bug would show up as a mismatch, not just a formula bug (the
formulas themselves are covered by services/discovery/tests/test_scout_metrics.py
and test_history_properties.py).

Checks, per wallet:
  1. trader file served (200) within the timeout
  2. per coin, sum(HL closedPnl) over the served trips' span ties out to
     sum(trip.gross_pnl_usd) within 0.5%
  3. no served trip spans a flip: replaying ONLY that trip's own
     [opened_ms, closed_ms] window for its coin through round_trips()
     yields exactly that one trip (same side, same net pnl)
  4. the served liquidation count (recent_fills, paginated across the span)
     equals the real HL liquidation fill count in that span
  5. for every trip with a cached funding read, served funding_usd equals
     positions.funding_by_trip on the real userFunding rows for its hold

usage: history_check.py <api_url> <token> <wallet1> <wallet2> <wallet3> [max_wait_s]
Prints PASS/FAIL per check; exit code = failures.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, ".")
sys.path.insert(0, "services/hl")
sys.path.insert(0, "services/discovery")

from discovery import positions as P  # noqa: E402
from discovery.scout import metrics as M  # noqa: E402
from hl.venue import HlVenue  # noqa: E402

API, TOKEN = sys.argv[1], sys.argv[2]
WALLETS = [w.lower() for w in sys.argv[3:6]]
# 900 s, not 180: an on-demand build of a dense wallet shares the per-IP HL budget with the
# live scout's hourly stats pass (COPYCAT_HL_BUCKET_PATH), and two of three wallets timed out
# at 180 s on 2026-10-15 while the build was progressing normally.
MAX_WAIT_S = float(sys.argv[6]) if len(sys.argv) > 6 else 900.0
fails = 0
venue = HlVenue()


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def call(method: str, path: str) -> Tuple[int, Any]:
    req = urllib.request.Request(API + path, method=method, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def wait_for_profile(address: str) -> Optional[Dict[str, Any]]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < MAX_WAIT_S:
        code, body = call("GET", f"/api/scout/traders/{address}")
        if code == 200:
            return body
        if code not in (202, 404):
            check(f"{address[:10]}: unexpected status while polling", False, f"{code} {body}")
            return None
        time.sleep(3)
    return None


def paginate_fills(address: str, lo_ms: int, hi_ms: int) -> List[Dict[str, Any]]:
    """Every served fill in [lo_ms, hi_ms], oldest first, walking `before_ms`
    pages backward until past lo_ms (same cursor rule as the real HL
    pagination: exclusive on the next page, never cuts a millisecond)."""
    out: List[Dict[str, Any]] = []
    before = hi_ms + 1
    guard = 0
    while guard < 200:
        guard += 1
        code, page = call("GET", f"/api/scout/traders/{address}/fills?before_ms={before}&limit=500")
        if code != 200 or not page:
            break
        out.extend(page)
        oldest = min(int(f["time_ms"]) for f in page)
        if oldest <= lo_ms or len(page) < 500:
            break
        before = oldest
    return [f for f in out if lo_ms <= int(f["time_ms"]) <= hi_ms]


def real_fills(address: str, lo_ms: int, hi_ms: int) -> List[Dict[str, Any]]:
    rows = venue.fills(address, lo_ms, hi_ms, aggregate_by_time=True)
    return rows or []


def real_funding(address: str, lo_ms: int, hi_ms: int) -> List[Dict[str, Any]]:
    if not hasattr(venue, "funding"):
        return []
    rows = venue.funding(address, lo_ms, hi_ms)
    return rows or []


def check_wallet(address: str) -> None:
    print(f"\n== {address} ==", flush=True)
    prof = wait_for_profile(address)
    check(f"{address[:10]}: trader file served", prof is not None, f"within {MAX_WAIT_S:.0f}s")
    if prof is None:
        return
    trips = prof.get("recent_trips") or []
    check(f"{address[:10]}: has at least one closed round trip", len(trips) > 0)
    if not trips:
        return

    lo_ms = min(t["opened_ms"] for t in trips)
    hi_ms = max(t["closed_ms"] for t in trips)
    ground = real_fills(address, lo_ms, hi_ms)
    funding = real_funding(address, lo_ms, hi_ms)
    check(f"{address[:10]}: real HL read for the served span returned fills", bool(ground), f"[{lo_ms}, {hi_ms}], {len(ground)} fills")

    # 2. per-coin closedPnl tie-out, summed per TRIP's own (opened_ms, closed_ms] span, not the
    # whole [lo_ms, hi_ms] window: `recent_trips` is capped at 100 total across every coin,
    # so for a hyperactive multi-coin wallet, some of a coin's OTHER trips inside [lo_ms, hi_ms]
    # can be pushed out of the cap by other coins -- comparing coin sums over the whole span
    # would then show a real-looking but false mismatch. Per-trip spans never have this problem:
    # round trips partition a coin's fills exactly, so whatever ground-truth fills a trip's own
    # span contains are indeed only that trip's.
    # The span is half-open on purpose. A flip (long to short with no flat) is ONE fill that
    # closes a trip and opens the next at the same ms; HL books its closedPnl on the position
    # being closed and positions.reconstruct puts it on the close event. Counting both ends
    # inclusively credited that fill to both trips: on 2026-10-15 a wallet with 20 XPL flips
    # read "served -30,706 vs HL -50,451" while every one of its 8 trips tied out exactly under
    # (opened, closed]. A fresh open's own fill has closedPnl 0, so excluding opened_ms loses nothing.
    ground_by_coin: Dict[str, List[Dict[str, Any]]] = {}
    for f in ground:
        ground_by_coin.setdefault(f["coin"], []).append(f)
    per_coin_served: Dict[str, float] = {}
    per_coin_real: Dict[str, float] = {}
    for t in trips:
        coin_fills = ground_by_coin.get(t["coin"], [])
        real_gross = sum(float(f.get("closed_pnl") or 0.0) for f in coin_fills
                         if t["opened_ms"] < int(f["time_ms"]) <= t["closed_ms"])
        per_coin_served[t["coin"]] = per_coin_served.get(t["coin"], 0.0) + t["gross_pnl_usd"]
        per_coin_real[t["coin"]] = per_coin_real.get(t["coin"], 0.0) + real_gross
    for coin, served in per_coin_served.items():
        real = per_coin_real.get(coin, 0.0)
        tol = max(0.01, abs(real) * 0.005)
        check(f"{address[:10]}: {coin} gross PnL ties out to HL closedPnl within 0.5%",
              abs(served - real) <= tol, f"served {served:.4f} vs HL {real:.4f}")

    # 3. no served trip spans a flip
    bad_flips = 0
    for t in trips:
        coin_fills = [f for f in ground if f["coin"] == t["coin"] and t["opened_ms"] <= int(f["time_ms"]) <= t["closed_ms"]]
        replay = M.round_trips(coin_fills)
        if not (len(replay) == 1 and replay[0].side == t["side"]):
            bad_flips += 1
    check(f"{address[:10]}: no served trip spans a flip ({len(trips)} trips replayed)", bad_flips == 0, f"{bad_flips} mismatched")

    # 4. liquidation count ties out (fills endpoint vs a real HL read, same span)
    served_fills = paginate_fills(address, lo_ms, hi_ms)
    served_liq = sum(1 for f in served_fills if f.get("liquidation"))
    real_liq_count, _ = M.real_liquidations(ground)
    check(f"{address[:10]}: liquidation fill count ties out", served_liq == real_liq_count,
          f"served {served_liq} vs HL {real_liq_count} (dir-prefix)")

    # 5. funding per trip
    funding_idx = P.index_funding_by_coin(funding)
    funding_checked = 0
    funding_bad = 0
    for t in trips:
        real_fund = P.funding_by_trip(funding_idx, t["coin"], t["opened_ms"], t["closed_ms"])
        if real_fund == 0.0 and t["funding_usd"] == 0.0:
            continue
        funding_checked += 1
        if abs(t["funding_usd"] - real_fund) > max(0.02, abs(real_fund) * 0.005):
            funding_bad += 1
    check(f"{address[:10]}: funding per trip ties out to real userFunding rows", funding_bad == 0,
          f"{funding_checked} trips checked, {funding_bad} mismatched")


def main() -> None:
    for address in WALLETS:
        check_wallet(address)
    print(f"\n{fails} check(s) failed")
    sys.exit(fails)


if __name__ == "__main__":
    main()
