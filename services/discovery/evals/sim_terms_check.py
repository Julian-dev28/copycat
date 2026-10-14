"""Live check of ScoutSimTerms (contract v16) against a THROWAWAY copycat stack
that reads real Hyperliquid data (sim_terms_check.sh starts it: temp data dir,
no account, no agent key, trading off, 40-wallet universe).

Proves, with real data and timings:
  1. GET /api/scout/sim-terms returns the documented default reference terms
     before anyone has ever called PUT
  2. PUT a "live-style" terms sheet (the operator's actual $15.20/exposure-target-50x
     numbers that produce the -200 band on the live board tonight) and the board
     re-ranks from cache (no new HL calls once stage B has run once)
  3. the default terms leave FEWER rows at Fit <= 20 than the live-style terms, and
     more wallets clearing >= 5 sim copies (the two symptoms the -200 band caused)
  4. switching back to a terms sheet the board was already simmed at is near-instant
     (no re-sim wait, just a republish)
  5. PUT validates like LeaderOverride (a bad value is 422)

usage: sim_terms_check.py <api_url> <token>
Prints PASS/FAIL per step; exit code = failures.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from discovery.scout import refresh as R

from contracts.models import ScoutSimTerms

API, TOKEN = sys.argv[1], sys.argv[2]
# The first full A+B+C build: real HL reads, 40 wallets. Alone it is minutes; sharing the per-IP
# budget with the live scout's hourly pass (COPYCAT_HL_BUCKET_PATH) a 40-wallet cold stage B alone
# measured 3,090 s on 2026-10-15, so a run beside a live stack sets COPYCAT_SIM_TERMS_REFRESH_WAIT_S.
REFRESH_WAIT_S = float(os.environ.get("COPYCAT_SIM_TERMS_REFRESH_WAIT_S") or 2400.0)
RESIM_WAIT_S = 300.0       # a cache-only resim of 40 wallets: measured ~0.07s/wallet, plus the
                           # scheduler tick (10 s) and a possible stage-B pass in front of it
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    req = urllib.request.Request(API + path, method=method, headers={"Authorization": f"Bearer {TOKEN}",
                                                                      "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
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


def status() -> Dict[str, Any]:
    return call("GET", "/api/scout/status")[1] or {}


def page(limit: int = 200) -> Dict[str, Any]:
    return call("GET", f"/api/scout/traders?limit={limit}")[1] or {}


def wait_for_hash(expected_hash: str, timeout_s: float) -> Tuple[bool, float]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        p = page(limit=1)
        if p.get("settings_hash") == expected_hash and not p.get("stale_settings"):
            return True, time.monotonic() - t0
        time.sleep(2)
    return False, time.monotonic() - t0


def fit_summary(rows: list) -> Dict[str, int]:
    low_fit = sum(1 for r in rows if ((r.get("score") or {}).get("copy_fit") or {}).get("value", 100) <= 20)
    trusted = sum(1 for r in rows if (r.get("score") or {}).get("sim_copies", 0) >= 5)
    starved = sum(1 for r in rows if (r.get("score") or {}).get("sim_copies", 0) == 0
                 and (r.get("score") or {}).get("sim_skipped_min_order", 0) > 0)
    return {"rows": len(rows), "fit_le_20": low_fit, "copies_ge_5": trusted, "min_order_starved": starved}


# ── 1. GET default terms ──────────────────────────────────────────────────────
code, default_terms = call("GET", "/api/scout/sim-terms")
check("1. GET /api/scout/sim-terms -> 200, the documented default", code == 200 and isinstance(default_terms, dict),
      f"{code} {default_terms}")
default = ScoutSimTerms.model_validate(default_terms) if isinstance(default_terms, dict) else ScoutSimTerms()
check("1. default is the reference ($1,000 / $100 / fixed 3x leverage, measured)",
      default == ScoutSimTerms(), str(default))

# ── 2. wait for the first full build (real HL) so stats exist to sim from ─────
code, _ = call("POST", "/api/scout/refresh")
check("2. refresh queued", code in (200, 409), f"POST /api/scout/refresh -> {code}")
t0 = time.monotonic()
st = status()
while st.get("state") == "running" and time.monotonic() - t0 < REFRESH_WAIT_S:
    time.sleep(5)
    st = status()
# "idle", not merely "not running": the 2026-10-15 03:37 run passed this on state=failed
# ("refresh stopped heartbeating (process died)") while the scout was alive, one stage C
# wallet 15 min into starved candle reads; every later check then ran on an empty board.
check("2. first build finished", st.get("state") == "idle",
      f"state={st.get('state')} error={st.get('error')} after {time.monotonic() - t0:.0f}s")

# ── 3. PUT the live-style terms (tonight's actual board: $15.20, target 50x capped 15x) ──
live_style = {"use_live_settings": False, "sim_equity_usd": 1_000.0, "allocation_usd": 15.20,
              "exposure_mode": "target", "target_leverage": 50, "leverage_mode": "fixed", "leverage": 15,
              "margin_mode": "isolated", "max_worse_entry_pct": 10.0, "small_account_mode": "concentrate"}
live_hash = R.terms_hash(ScoutSimTerms.model_validate(live_style))
code, put_back = call("PUT", "/api/scout/sim-terms", live_style)
check("3. PUT live-style terms -> 200, echoes what was sent", code == 200 and put_back == live_style,
      f"{code} {put_back}")
ok, elapsed = wait_for_hash(live_hash, RESIM_WAIT_S)
check(f"3. board re-ranked at the live-style terms within {RESIM_WAIT_S:.0f}s", ok, f"{elapsed:.1f}s")
live_rows = page().get("rows", [])
live_summary = fit_summary(live_rows)
print(f"    live-style summary: {live_summary}")

# ── 4. PUT the default terms back; compare the Fit distribution ───────────────
default_hash = R.terms_hash(ScoutSimTerms())
code, put_default = call("PUT", "/api/scout/sim-terms", ScoutSimTerms().model_dump(mode="json"))
check("4. PUT default terms -> 200", code == 200, f"{code}")
ok, elapsed = wait_for_hash(default_hash, RESIM_WAIT_S)
check(f"4. board re-ranked at the default terms within {RESIM_WAIT_S:.0f}s", ok, f"{elapsed:.1f}s")
default_rows = page().get("rows", [])
default_summary = fit_summary(default_rows)
print(f"    default summary:    {default_summary}")

check("4. default terms leave FEWER (or equal) rows at Fit <= 20 than the live-style terms",
      default_summary["fit_le_20"] <= live_summary["fit_le_20"],
      f"default={default_summary['fit_le_20']} live-style={live_summary['fit_le_20']}")
check("4. default terms clear >= 5 sim copies for MORE (or equal) wallets than the live-style terms",
      default_summary["copies_ge_5"] >= live_summary["copies_ge_5"],
      f"default={default_summary['copies_ge_5']} live-style={live_summary['copies_ge_5']}")
check("4. default terms starve fewer (or equal) wallets on the $10.50 minimum",
      default_summary["min_order_starved"] <= live_summary["min_order_starved"],
      f"default={default_summary['min_order_starved']} live-style={live_summary['min_order_starved']}")

# ── 5. switching back to an already-cached hash is near-instant ──────────────
t0 = time.monotonic()
code, _ = call("PUT", "/api/scout/sim-terms", live_style)
ok, elapsed = wait_for_hash(live_hash, 60.0)   # already simmed at this hash in step 3: no re-sim needed
check("5. switching back to the live-style terms (already cached) is near-instant", ok and elapsed < 60.0,
      f"{elapsed:.1f}s")

# ── 6. validation mirrors LeaderOverride ──────────────────────────────────────
code, body = call("PUT", "/api/scout/sim-terms", {**live_style, "leverage": 999})
check("6. leverage over the cap -> 422", code == 422, f"{code} {body}")
code, body = call("PUT", "/api/scout/sim-terms", {**live_style, "allocation_usd": 1.0})
check("6. allocation under the $10.50 minimum -> 422", code == 422, f"{code} {body}")

print(f"\n{fails} check(s) failed")
sys.exit(fails)
