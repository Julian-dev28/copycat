"""CLI: `python -m discovery.scout refresh|serve|top`.

    refresh [--limit-b N] [--limit-c N] [--stages ABC] [--partial]   one synchronous refresh, prints the report
    serve                                                           the scheduler (make dev / compose `scout`)
    top [--n 20] [--sort fit] [--window 30d]                        print the served board

Env: COPYCAT_SKIP_DOTENV=1 skips ./.env; COPYCAT_AGENT_KEY is always dropped
after loading (Scout never signs). HL reads run at background priority.
Settings come from $COPYCAT_DATA_DIR/settings.json, re-read every tick; a
missing or broken file keeps the last good copy (defaults before the first).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from contracts.models import Settings


def _env() -> None:
    if os.environ.get("COPYCAT_SKIP_DOTENV") != "1":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    os.environ.pop("COPYCAT_AGENT_KEY", None)
    os.environ["COPYCAT_HL_PRIORITY"] = "background"


def settings_reader(path: Optional[Path] = None) -> Callable[[], Settings]:
    """Settings provider: settings.json, last good copy on a bad read."""
    last = {"s": Settings()}

    def read() -> Settings:
        p = path or Path(os.environ.get("COPYCAT_DATA_DIR", "./data")) / "settings.json"
        try:
            last["s"] = Settings.model_validate(json.loads(p.read_text()))
        except FileNotFoundError:
            pass
        except Exception as exc:
            logging.getLogger(__name__).warning("scout: settings.json unreadable (%s), keeping last good", exc)
        return last["s"]
    return read


def _equity() -> float:
    from . import config as C
    return C.DEFAULT_SIM_EQUITY_USD


def main(argv=None) -> int:
    _env()
    p = argparse.ArgumentParser(prog="discovery.scout")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--stages", default="ABC")
    r.add_argument("--limit-b", type=int)
    r.add_argument("--limit-c", type=int)
    r.add_argument("--partial", action="store_true", help="publish even if stage C did not finish every wallet")
    sub.add_parser("serve")
    t = sub.add_parser("top")
    t.add_argument("--n", type=int, default=20)
    t.add_argument("--sort", default="fit")
    t.add_argument("--window", default="30d")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from . import public
    from . import refresh as R
    if a.cmd == "serve":
        print(f"scout serve: progress in {public.C.progress_log_path()} "
              f"(tail -f {public.C.progress_log_path()})")
        public.serve(settings_reader(), _equity)
        return 0
    if a.cmd == "refresh":
        public.use_background_priority()
        t0 = time.time()
        rep = R.run_refresh(public._default_venue(), settings_reader()(), _equity(),
                            R.RefreshOptions(stages=tuple(a.stages.upper()), limit_b=a.limit_b, limit_c=a.limit_c,
                                             allow_partial=a.partial, kind="cli"),
                            terms=public.scout_sim_terms_get())
        print(json.dumps(rep.__dict__, indent=2))
        print(f"scout refresh: {time.time() - t0:.1f}s")
        return 0
    page = public.scout_page({"sort": a.sort, "window": a.window, "limit": a.n})
    print(f"refresh {page.refresh_id[:8]} hash {page.settings_hash} cohort {page.cohort_size} "
          f"stale_settings={page.stale_settings}")
    for i, row in enumerate(page.rows, 1):
        s = row.score
        fit = s.copy_fit.value if s.copy_fit else float("nan")
        print(f"{i:>3} {row.address} fit={fit:5.1f} sim={s.sim_return_pct:7.2f}% dd={s.sim_max_drawdown_pct:6.2f}% "
              f"pnl30={row.perf[2].pnl_usd:>12,.0f} sharpe={row.risk_30d.sharpe} win={row.trades_30d.win_rate_pct} "
              f"trips={row.trades_30d.trips} style={row.style.value if row.style else '-'} "
              f"flags={','.join(row.flags) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
