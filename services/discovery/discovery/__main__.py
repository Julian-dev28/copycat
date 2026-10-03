"""CLI: `python -m discovery --equity 100 --top 20`

Starts a run, polls it to completion printing progress, then prints a
ranked table. All formatting here is plain deterministic string work --
no model calls, nothing non-reproducible.
"""
from __future__ import annotations

import argparse
import sys
import time

from contracts.models import Settings

from . import config, public


def _parse_args(argv: list) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="discovery", description="Rank HL leaders by what copying them "
                                 "would have earned you, not by their own PnL.")
    p.add_argument("--equity", type=float, required=True, help="simulated copier equity in USD")
    p.add_argument("--top", type=int, default=config.DEFAULT_TOP_N, help="top_n leaderboard candidates")
    p.add_argument("--days", type=int, default=config.DEFAULT_WINDOW_DAYS, help="fills/candle window in days")
    p.add_argument("--min-account-value", type=float, default=config.DEFAULT_MIN_ACCOUNT_VALUE_USD)
    p.add_argument("--min-volume", type=float, default=config.DEFAULT_MIN_VOLUME_30D_USD)
    p.add_argument("--poll-s", type=float, default=2.0, help="progress poll interval while a run executes")
    return p.parse_args(argv)


def _fmt_row(rank: int, r) -> str:
    flags = ",".join(r.flags) if r.flags else "-"
    hold = f"{r.median_hold_h:.1f}h" if r.median_hold_h is not None else "n/a"
    return (f"{rank:>3}  {r.address}  score={r.score:>8.2f}  "
            f"ret={r.sim_return_pct:>7.2f}%  dd={r.sim_max_drawdown_pct:>7.2f}%  "
            f"copies={r.sim_copies:>3}  liq={r.sim_liquidations}  "
            f"fees=${r.sim_fees_usd:>6.2f}  hold={hold:>7}  flags={flags}")


def main(argv=None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings()

    run_id = public.start_run(settings, args.equity, top_n=args.top, window_days=args.days,
                               min_account_value_usd=args.min_account_value,
                               min_volume_30d_usd=args.min_volume)
    print(f"discovery: run {run_id} started (equity=${args.equity}, top_n={args.top}, "
          f"window={args.days}d)")

    while True:
        run = public.get_run(run_id)
        if run is None:
            print("discovery: run vanished unexpectedly", file=sys.stderr)
            return 1
        print(f"discovery: {run.scored}/{run.candidates or '?'} scored, status={run.status}")
        if run.status in ("done", "failed"):
            break
        time.sleep(args.poll_s)

    if run.status == "failed":
        print(f"discovery: run failed: {run.error}", file=sys.stderr)
        return 1

    ranked = sorted(run.results, key=lambda r: r.score, reverse=True)
    print(f"\n{'#':>3}  {'address':<42}  {'score':>8}  {'ret%':>8}  {'dd%':>8}  "
          f"{'cop':>7}  liq  {'fees':>7}  {'hold':>7}  flags")
    for i, r in enumerate(ranked, start=1):
        print(_fmt_row(i, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
