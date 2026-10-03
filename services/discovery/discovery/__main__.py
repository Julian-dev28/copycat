"""CLI.

    python -m discovery --equity 100 [--top 20] [--days 30] [--include-hft]
        start a run, print progress with an ETA, then the ranked table
    python -m discovery worker --run-id <id>
        execute an already-created run (what start_run(mode="subprocess") spawns)
    python -m discovery trace --wallet 0x.. [--equity 100] [--days 30]
        one wallet: reconstructed positions vs his live account, plus the
        copy-sim trace (copies, sizes, liquidations)

Plain deterministic formatting, no network beyond hl reads.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from contracts.models import Settings

from . import config, public


def _fmt_row(rank: int, r) -> str:
    flags = ",".join(r.flags) if r.flags else "-"
    return (f"{rank:>3}  {r.address}  {r.score:>8.2f}  {r.sim_return_pct:>8.2f}  {r.sim_max_drawdown_pct:>7.2f}  "
            f"{r.sim_liquidations:>3}  {r.sim_copies:>4}  {r.fills_30d:>6}  {r.opens_per_day:>6.1f}  {flags}")


def print_table(run, out=sys.stdout) -> None:
    ranked = sorted(run.results, key=lambda r: r.score, reverse=True)
    print(f"\n{'#':>3}  {'address':<42}  {'score':>8}  {'ret%':>8}  {'dd%':>7}  {'liq':>3}  {'cop':>4}  "
          f"{'fills':>6}  {'opd':>6}  flags", file=out)
    for i, r in enumerate(ranked, start=1):
        print(_fmt_row(i, r), file=out)


def progress_line(run, elapsed_s: float) -> str:
    from .runner import eta_s
    eta = eta_s(run.scored, run.candidates, elapsed_s)
    eta_txt = "?" if eta is None else f"{eta:.0f}s"
    return (f"discovery: {run.scored}/{run.candidates or '?'} scored, {elapsed_s:.0f}s elapsed, "
            f"eta {eta_txt}, status={run.status}")


def _run(argv) -> int:
    p = argparse.ArgumentParser(prog="discovery", description="Rank HL leaders by what copying them "
                                "would have earned you, not by their own PnL.")
    p.add_argument("--equity", type=float, required=True, help="simulated copier equity in USD")
    p.add_argument("--top", type=int, default=config.DEFAULT_TOP_N)
    p.add_argument("--days", type=int, default=config.DEFAULT_WINDOW_DAYS)
    p.add_argument("--min-account-value", type=float, default=config.DEFAULT_MIN_ACCOUNT_VALUE_USD)
    p.add_argument("--min-volume", type=float, default=config.DEFAULT_MIN_VOLUME_30D_USD)
    p.add_argument("--include-hft", action="store_true", help="simulate wallets with >100 opens/day too")
    p.add_argument("--poll-s", type=float, default=2.0)
    a = p.parse_args(argv)
    started = time.time()
    run_id = public.start_run(Settings(), a.equity, top_n=a.top, window_days=a.days,
                              min_account_value_usd=a.min_account_value, min_volume_30d_usd=a.min_volume,
                              include_hft=a.include_hft)
    print(f"discovery: run {run_id} started (equity=${a.equity}, top_n={a.top}, window={a.days}d)")
    last = None
    while True:
        run = public.get_run(run_id)
        if run is None:
            print("discovery: run vanished", file=sys.stderr)
            return 1
        line = progress_line(run, time.time() - started)
        if (run.scored, run.candidates, run.status) != last:
            print(line, flush=True)
            last = (run.scored, run.candidates, run.status)
        if run.status in ("done", "failed"):
            break
        time.sleep(a.poll_s)
    if run.status == "failed":
        print(f"discovery: run failed: {run.error}", file=sys.stderr)
        return 1
    print(f"discovery: done in {time.time() - started:.1f}s")
    print_table(run)
    return 0


def _worker(argv) -> int:
    p = argparse.ArgumentParser(prog="discovery worker")
    p.add_argument("--run-id", required=True)
    a = p.parse_args(argv)
    public.run_worker(a.run_id)
    run = public.get_run(a.run_id)
    return 0 if run is not None and run.status == "done" else 1


def _trace(argv) -> int:
    from . import tracing
    p = argparse.ArgumentParser(prog="discovery trace")
    p.add_argument("--wallet", required=True)
    p.add_argument("--equity", type=float, default=100.0)
    p.add_argument("--days", type=int, default=config.DEFAULT_WINDOW_DAYS)
    p.add_argument("--max-lines", type=int, default=60)
    a = p.parse_args(argv)
    public.use_background_priority()
    for line in tracing.trace_wallet(a.wallet, Settings(), a.equity, a.days, max_lines=a.max_lines):
        print(line)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if argv and argv[0] == "worker":
        logging.getLogger("discovery").setLevel(logging.INFO)
        return _worker(argv[1:])
    if argv and argv[0] == "trace":
        return _trace(argv[1:])
    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
