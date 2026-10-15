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
  1. the cold pass admits the whole cohort (nothing deferred by the budget);
     wallets that failed are counted and each failure's reason printed (a
     read the shared bucket could not serve within hl.http's 30 s wait fails
     the wallet, which the next pass rebuilds)
  2. the warm pass's wall clock NET OF BUCKET WAIT is inside budget. The wall
     clock subtracts stage_b_summary.bucket_wait_s, the seconds the pass
     slept waiting for HL budget (hl.rate_limit.waited_s): beside a live
     engine every call queues on the shared per-IP bucket, 378 s of wall
     clock for ~100 s of work on 2026-10-15, and that queue is the engine's,
     not the warm path's
  3. the warm PATH's weight/wallet (p50 over the wallets that skipped the
     slow-cadence set, stage_b_summary.warm_weight_p50) is inside budget
     (weight = what HL metered for the pages that came back, HlVenue.last_read:
     a warm wallet is portfolio 20 + a 1-page tail 20 + 1 per 20 rows, ~41;
     until 2026-10-15 the budget billed the 2000-row page cap, 120 per page,
     so this check could not pass with a correct warm path). The all-wallet
     median is printed next to it but not judged: how many wallets take the
     full set in a warm pass is how many traded or failed during the cold
     pass, a function of that pass's length (bucket contention), not of the
     warm path (11/20 on 2026-10-15 put the all-wallet p50 at 117)
  4. a warm-path build really is cheaper than a cold build: the warm pass's
     warm_weight_p50 against the cold pass's weight_p50 (every cold build
     takes the full set). Percentiles are over BUILT wallets: a build that
     failed burned its weight before the read that gave up and is neither a
     cold nor a warm build (8 of 20 on 2026-10-15 09:40 dragged the all-wallet
     cold median to 258 and pushed the warm one to 412)
  5. not every warm-pass wallet took the slow-cadence set
     (stage_b_summary.full_count < n) -- the whole point of the cadence
  6. the ETA (scout_refresh.eta_s) is None early in a pass and a real number
     once the pass clears refresh.eta_s's honesty gate

Beside a live copycat (the only way to run it on a trading host) the eval is a
second background caller on the shared bucket: the live scout's own stats pass
slows down and some of its reads give up after 30 s (8 wallets of 56 on
2026-10-15 07:44 to 08:34, retried by its next pass); the engine, foreground
priority, drew no 429. That is the price of a real-HL eval on that host.

usage: stats_budget_check.py <data_dir> [universe]
Prints PASS/FAIL per check, plus the measured numbers; exit code = failures.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]   # services/discovery/evals/<this file> -> repo root
DATA_DIR = Path(".")        # set by main() from argv (import-safe: the tests import the pure helpers)
UNIVERSE = 40
DB = DATA_DIR / "discovery.db"
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

FAILED_RE = re.compile(r"scout stage B: (0x[0-9a-fA-F]{40}) failed \(\d+ in a row\): (.*)$")
EXHAUSTED_RE = re.compile(r"rate budget exhausted for (\S+) \(weight=\d+, waited [0-9.]+s\)")


def failure_lines(out: str) -> Tuple[List[str], Dict[str, int]]:
    """From a pass's log output: each failed wallet as "<address>: <reason>",
    and how many reads of each type the shared bucket could not serve within
    hl.http's wait ("rate budget exhausted ... returning None"). Those
    give-ups are what fails a wallet beside a live copycat; the 2026-10-15
    07:35 run lost 4 of 20 cold builds to them and this eval had thrown the
    output away (it printed the pass output only on a non-zero exit)."""
    failed: List[str] = []
    exhausted: Dict[str, int] = {}
    for line in out.splitlines():
        m = FAILED_RE.search(line)
        if m:
            failed.append(f"{m.group(1)}: {m.group(2).strip()}")
        m = EXHAUSTED_RE.search(line)
        if m:
            exhausted[m.group(1)] = exhausted.get(m.group(1), 0) + 1
    return failed, exhausted


def run_pass(label: str) -> Tuple[Dict[str, Any], float, List[Sample]]:
    """One `scout refresh --stages AB`, sampling scout_refresh (done, total,
    eta_s) every 150ms while it runs. Returns (RefreshReport dict, wall_s,
    samples). Prints every failed wallet's reason and the bucket give-ups
    per read type (failure_lines) before returning."""
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
    failed, exhausted = failure_lines(out)
    for f in failed:
        print(f"  {label} pass failed wallet: {f}")
    if exhausted:
        print(f"  {label} pass bucket give-ups (rate budget exhausted): "
              + ", ".join(f"{k}={v}" for k, v in sorted(exhausted.items())))
    return rep, wall_s, samples


def eta_gate_evidence(samples: List[Sample]) -> Tuple[bool, bool]:
    """(saw a sample before the gate with no eta, saw a sample after the gate
    with a real eta). Mirrors refresh.eta_s's own gate: hidden while
    done < 10 OR done < total * 0.10 (both gates must be met)."""
    before = [(d, t, e) for d, t, e in samples if t > 0 and d >= 1 and (d < 10 or d < t * 0.10)]
    after = [(d, t, e) for d, t, e in samples if t > 0 and d >= 10 and d >= t * 0.10]
    return any(e is None for _, _, e in before), any(e is not None for _, _, e in after)


def warm_path_check(summary: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Check 3: (ok, detail). Judges `warm_weight_p50`, the median over the
    wallets that skipped the slow-cadence set; a summary written by a scout
    from before that field (or a pass where every wallet took the full set,
    None) falls back to the all-wallet median, which then fails for the
    right reason: no warm path ran."""
    if not summary:
        return False, "no summary"
    n, full = int(summary["n"]), int(summary["full_count"])
    built = int(summary.get("built", n))
    warm_p50 = summary.get("warm_weight_p50")
    fallback = warm_p50 is None
    judged = float(summary["weight_p50"] if fallback else warm_p50)
    detail = (f"warm path p50 {judged:g} over {built - full} wallet(s)" if not fallback
              else f"no warm-path median ({'every wallet took the full set' if full >= built else 'older summary'}), "
                   f"judging the all-wallet p50 {judged:g}")
    detail += (f"; full set on {full}/{built} built (p50 {summary.get('full_weight_p50')}); "
               f"all built: p50 {summary['weight_p50']}; failed {summary.get('failed', 0)} of {n}")
    return judged <= WARM_WEIGHT_P50_MAX, detail


def cheaper_check(cold: Optional[Dict[str, Any]], warm: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Check 4: a warm-path build costs less than a cold build. Like with
    like: the warm pass's `warm_weight_p50` (its warm-path wallets) against
    the cold pass's `weight_p50` (every cold build takes the full set).
    The all-wallet medians are not comparable: on 2026-10-15 8 of 20 cold
    builds failed at a read the bucket could not serve, their small burned
    weight pulled the cold median to 258 and their heavy rebuilds pushed the
    warm median to 412, while the warm path cost 40 and a cold build 242."""
    if not cold or not warm:
        return False, "no summary"
    warm_p50 = warm.get("warm_weight_p50")
    if warm_p50 is None:
        warm_p50 = warm["weight_p50"]      # no warm path ran (or an older summary): the all-wallet median
    ok = float(warm_p50) < float(cold["weight_p50"])
    return ok, (f"cold build p50 {cold['weight_p50']} over {cold.get('built', cold['n'])} built vs warm path p50 "
                f"{warm_p50}; all-wallet medians cold {cold['weight_p50']} warm {warm['weight_p50']}")


def main() -> int:
    global DATA_DIR, UNIVERSE, DB
    DATA_DIR = Path(sys.argv[1])
    UNIVERSE = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    DB = DATA_DIR / "discovery.db"
    print(f"stats_budget_check: universe={UNIVERSE} data_dir={DATA_DIR}")

    cold_rep, cold_s, cold_samples = run_pass("cold")
    with _conn() as conn:
        cold_summary = _meta(conn, "stage_b_summary")
    print(f"cold pass: {cold_s:.1f}s weight_b={cold_rep['weight_b']:.0f} stats_done={cold_rep['stats_done']} "
         f"failed={cold_rep['stats_failed']} deferred={cold_rep['stats_deferred']} summary={json.dumps(cold_summary)}")

    warm_rep, warm_s, warm_samples = run_pass("warm")
    with _conn() as conn:
        warm_summary = _meta(conn, "stage_b_summary")
    print(f"warm pass: {warm_s:.1f}s weight_b={warm_rep['weight_b']:.0f} stats_done={warm_rep['stats_done']} "
         f"failed={warm_rep['stats_failed']} deferred={warm_rep['stats_deferred']} summary={json.dumps(warm_summary)}")

    check("1. cold pass admitted the whole cohort (nothing deferred)", cold_rep["stats_deferred"] == 0,
         f"done={cold_rep['stats_done']} failed={cold_rep['stats_failed']} deferred={cold_rep['stats_deferred']} "
         f"universe={cold_rep['universe']}")

    warm_wait = float((warm_summary or {}).get("bucket_wait_s") or 0.0)
    check("2. warm pass wall clock net of bucket wait <= 4 min", warm_s - warm_wait <= WARM_WALL_S_MAX,
         f"{warm_s:.1f}s wall, {warm_wait:.1f}s waiting for HL budget, {warm_s - warm_wait:.1f}s of work")

    check("3. warm-path weight p50/wallet <= 60 (wallets that skipped the full set)", *warm_path_check(warm_summary))

    check("4. a warm-path build is cheaper than a cold build (warm path p50 < cold build p50)",
          *cheaper_check(cold_summary, warm_summary))

    ok_full = warm_summary is not None and warm_summary["full_count"] < warm_summary["n"]
    check("5. not every warm-pass wallet took the slow-cadence set", ok_full,
         f"full={warm_summary and warm_summary['full_count']}/{warm_summary and warm_summary['n']}")

    all_samples = cold_samples + warm_samples
    absent, present = eta_gate_evidence(all_samples)
    check("6. ETA absent early in a pass (below the gate)", absent, f"{len(all_samples)} samples observed")
    check("7. ETA present once the gate opens", present)

    print(f"\n{fails} check(s) failed")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
