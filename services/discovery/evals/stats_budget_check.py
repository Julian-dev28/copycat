"""Live check of the stage-B warm path (indexing tightening, 2026-10), against a
THROWAWAY copycat data dir that reads real Hyperliquid data
(stats_budget_check.sh starts it: temp dir, no account, no agent key,
background HL priority -- nothing it does can place an order).

Runs `python -m discovery.scout refresh --stages AB` twice back to back over a
COPYCAT_SCOUT_UNIVERSE wallet cohort (default 40): the first pass is COLD
(every wallet built for the first time: portfolio, account_state, extras, the
fills backfill, funding, the liquidation backfill); the second pass, run
immediately after, is WARM (every wallet already has stats, no new fills
landed in between -- the cheap path should skip the slow-cadence set for all
but a wallet whose cadence happened to land exactly on this pass).

Proves, with real data and real timings:
  1. the cold pass actually builds the whole cohort (nothing deferred)
  2. the warm pass's wall clock NET OF BUCKET WAIT and weight/wallet (p50) are
     inside budget (weight = what HL metered for the pages that came back,
     HlVenue.last_read: a warm wallet is portfolio 20 + a 1-page tail 20 + 1
     per 20 rows, ~41; until 2026-10-15 the budget billed the 2000-row page
     cap, 120 per page, so this check could not pass with a correct warm path.
     The wall clock subtracts stage_b_summary.bucket_wait_s, the seconds the
     pass slept waiting for HL budget (hl.rate_limit.waited_s): beside a live
     engine every call queues on the shared per-IP bucket, 378 s of wall clock
     for ~100 s of work on 2026-10-15, and that queue is the engine's, not
     the warm path's)
  3. the warm pass really is cheaper than the cold one (weight p50 dropped)
  4. most of the warm pass's wallets skipped the slow-cadence set
     (stage_b_summary.full_count < n) -- the whole point of the cadence
  5. the ETA (scout_refresh.eta_s) is None early in a pass and a real number
     once the pass clears refresh.eta_s's honesty gate

usage: stats_budget_check.py <data_dir> [universe]
Prints PASS/FAIL per check, plus the measured numbers; exit code = failures.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(sys.argv[1])
UNIVERSE = int(sys.argv[2]) if len(sys.argv) > 2 else 40
DB = DATA_DIR / "discovery.db"
ROOT = Path(__file__).resolve().parents[3]   # services/discovery/evals/<this file> -> repo root
WARM_WALL_S_MAX = 240.0     # brief: warm pass <= 4 min on the 40-wallet throwaway stack
WARM_WEIGHT_P50_MAX = 60.0  # brief: warm pass <= 60 weight/wallet at p50

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _meta(conn: sqlite3.Connection, k: str) -> Any:
    r = conn.execute("SELECT v FROM scout_meta WHERE k = ?", (k,)).fetchone()
    return json.loads(r["v"]) if r else None


def _latest_refresh(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_refresh ORDER BY started_ms DESC LIMIT 1").fetchone()
    return dict(r) if r else None


Sample = Tuple[int, int, Optional[float]]   # (done, total, eta_s)


def run_pass(label: str) -> Tuple[Dict[str, Any], float, List[Sample]]:
    """One `scout refresh --stages AB`, sampling scout_refresh (done, total,
    eta_s) every 150ms while it runs. Returns (RefreshReport dict, wall_s,
    samples)."""
    t0 = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "discovery.scout", "refresh", "--stages", "AB"],
        cwd=ROOT, env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    samples: List[Sample] = []
    for _ in range(200):          # DB may not exist for an instant at the very start of pass 1
        if DB.exists():
            break
        time.sleep(0.05)
    while proc.poll() is None:
        try:
            conn = _conn()
            try:
                r = _latest_refresh(conn)
                if r and r["state"] == "running" and r["stage"] == "stats":
                    samples.append((int(r["done"] or 0), int(r["total"] or 0), r["eta_s"]))
            finally:
                conn.close()
        except sqlite3.OperationalError:
            pass   # db mid-write: skip this sample, not a failure
        time.sleep(0.15)
    out, _ = proc.communicate()
    wall_s = time.monotonic() - t0
    if proc.returncode != 0:
        print(out)
        raise RuntimeError(f"{label} pass: `scout refresh` exited {proc.returncode}")
    # The report is the LAST pretty-printed JSON object in the output (`scout refresh`
    # prints it with indent=2, so it starts on a line that is exactly "{"). Log lines
    # before it may contain braces too: stage B's INFO summary did, and the first "{"
    # in the stream broke the first recorded run of this eval (2026-10-14).
    start = out.rindex("\n{\n") + 1
    end = out.index("\n}", start) + 2
    rep = json.loads(out[start:end])
    return rep, wall_s, samples


def eta_gate_evidence(samples: List[Sample]) -> Tuple[bool, bool]:
    """(saw a sample before the gate with no eta, saw a sample after the gate
    with a real eta). Mirrors refresh.eta_s's own gate: hidden while
    done < 10 OR done < total * 0.10 (both gates must be met)."""
    before = [(d, t, e) for d, t, e in samples if t > 0 and d >= 1 and (d < 10 or d < t * 0.10)]
    after = [(d, t, e) for d, t, e in samples if t > 0 and d >= 10 and d >= t * 0.10]
    return any(e is None for _, _, e in before), any(e is not None for _, _, e in after)


def main() -> int:
    print(f"stats_budget_check: universe={UNIVERSE} data_dir={DATA_DIR}")

    cold_rep, cold_s, cold_samples = run_pass("cold")
    with _conn() as conn:
        cold_summary = _meta(conn, "stage_b_summary")
    print(f"cold pass: {cold_s:.1f}s weight_b={cold_rep['weight_b']:.0f} "
         f"stats_done={cold_rep['stats_done']} deferred={cold_rep['stats_deferred']} summary={json.dumps(cold_summary)}")

    warm_rep, warm_s, warm_samples = run_pass("warm")
    with _conn() as conn:
        warm_summary = _meta(conn, "stage_b_summary")
    print(f"warm pass: {warm_s:.1f}s weight_b={warm_rep['weight_b']:.0f} "
         f"stats_done={warm_rep['stats_done']} deferred={warm_rep['stats_deferred']} summary={json.dumps(warm_summary)}")

    check("1. cold pass built the whole cohort (nothing deferred)", cold_rep["stats_deferred"] == 0,
         f"done={cold_rep['stats_done']} deferred={cold_rep['stats_deferred']} universe={cold_rep['universe']}")

    warm_wait = float((warm_summary or {}).get("bucket_wait_s") or 0.0)
    check("2. warm pass wall clock net of bucket wait <= 4 min", warm_s - warm_wait <= WARM_WALL_S_MAX,
         f"{warm_s:.1f}s wall, {warm_wait:.1f}s waiting for HL budget, {warm_s - warm_wait:.1f}s of work")

    ok_p50 = warm_summary is not None and warm_summary["weight_p50"] <= WARM_WEIGHT_P50_MAX
    check("3. warm pass weight p50/wallet <= 60", ok_p50,
         f"{warm_summary['weight_p50'] if warm_summary else 'no summary'}")

    ok_cheaper = (cold_summary is not None and warm_summary is not None
                 and warm_summary["weight_p50"] < cold_summary["weight_p50"])
    check("4. warm weight p50 is lower than cold weight p50", ok_cheaper,
         f"cold={cold_summary and cold_summary['weight_p50']} warm={warm_summary and warm_summary['weight_p50']}")

    ok_full = warm_summary is not None and warm_summary["full_count"] < warm_summary["n"]
    check("5. most warm-pass wallets skipped the slow-cadence set", ok_full,
         f"full={warm_summary and warm_summary['full_count']}/{warm_summary and warm_summary['n']}")

    all_samples = cold_samples + warm_samples
    absent, present = eta_gate_evidence(all_samples)
    check("6. ETA absent early in a pass (below the gate)", absent, f"{len(all_samples)} samples observed")
    check("7. ETA present once the gate opens", present)

    print(f"\n{fails} check(s) failed")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
