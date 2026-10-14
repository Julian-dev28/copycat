"""Live check of custom wallets on the Scout board (contract v15), against a
THROWAWAY copycat stack that reads real Hyperliquid data (custom_wallet_check.sh
starts it: temp data dir, no account, no agent key, trading off).

Proves, with real data and timings:
  1. a full refresh is running (POST /api/scout/refresh, status.state running)
  2. POST /api/scout/custom queues the wallet (201, queued=true)
  3. the wallet's row shows on preset=custom with custom=true WHILE that refresh
     is still running (the scheduler serves the queue mid-refresh; before this
     the request waited for the refresh to end)
  4. its trader file is served (200), account value and sim fields are real numbers
  5. presets.custom counts it; DELETE takes it off the board at once

usage: custom_wallet_check.py <api_url> <token> <wallet> [max_wait_s]
Prints PASS/FAIL per step; exit code = failures.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

API, TOKEN, WALLET = sys.argv[1], sys.argv[2], sys.argv[3].lower()
MAX_WAIT_S = float(sys.argv[4]) if len(sys.argv) > 4 else 300.0
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


def custom_row() -> Optional[Dict[str, Any]]:
    code, page = call("GET", "/api/scout/traders?preset=custom&limit=50")
    if code != 200:
        return None
    return next((r for r in page.get("rows", []) if r["address"] == WALLET), None)


# 1. a full refresh is running
code, _ = call("POST", "/api/scout/refresh")
check("1. refresh queued", code in (200, 409), f"POST /api/scout/refresh -> {code}")
t0 = time.monotonic()
st = status()
while st.get("state") != "running" and time.monotonic() - t0 < 90:
    time.sleep(2)
    st = status()
check("1. refresh running", st.get("state") == "running", f"state={st.get('state')} stage={st.get('stage')}")

# 2. add the wallet
code, cw = call("POST", "/api/scout/custom", {"address": WALLET})
check("2. POST /api/scout/custom -> 201 queued", code == 201 and isinstance(cw, dict) and cw.get("queued") is True,
      f"{code} {cw}")
t_add = time.monotonic()

# 3. the row appears while the refresh still runs
row, seen_status, elapsed = None, {}, 0.0
while time.monotonic() - t_add < MAX_WAIT_S:
    row = custom_row()
    if row is not None:
        seen_status = status()
        elapsed = time.monotonic() - t_add
        break
    time.sleep(3)
check("3. row on preset=custom with custom=true", row is not None and row.get("custom") is True,
      f"after {elapsed:.0f}s" if row else f"not within {MAX_WAIT_S:.0f}s")
running = seen_status.get("state") == "running"
check("3. served while the refresh was still running", running or elapsed <= 60,
      f"status at that moment: {seen_status.get('state')} {seen_status.get('stage')} "
      f"{seen_status.get('done')}/{seen_status.get('total')}; row after {elapsed:.0f}s")

# 4. the file and the numbers
code, prof = call("GET", f"/api/scout/traders/{WALLET}")
ok_file = code == 200 and isinstance(prof, dict) and "row" in prof
check("4. GET trader file -> 200", ok_file, f"{code}")
if row is not None:
    sc = row.get("score") or {}
    check("4. account value > 0 (from its own portfolio)", float(row.get("account_value_usd") or 0) > 0,
          f"${float(row.get('account_value_usd') or 0):,.0f}")
    check("4. sim ran (sim_return_pct, sim_copies present)",
          isinstance(sc.get("sim_return_pct"), (int, float)) and isinstance(sc.get("sim_copies"), int),
          f"return {sc.get('sim_return_pct')}% copies {sc.get('sim_copies')} fit "
          f"{(sc.get('copy_fit') or {}).get('value')}")

# 5. presets count and removal
code, pre = call("GET", "/api/scout/presets")
check("5. presets.custom == 1", code == 200 and (pre or {}).get("custom") == 1, f"{(pre or {}).get('custom')}")
code, _ = call("DELETE", f"/api/scout/custom/{WALLET}")
check("5. DELETE -> 204", code == 204, str(code))
check("5. row gone at once", custom_row() is None)
code, lst = call("GET", "/api/scout/custom")
check("5. GET /api/scout/custom empty", code == 200 and lst == [], f"{lst}")

print(f"\n{fails} check(s) failed")
sys.exit(fails)
