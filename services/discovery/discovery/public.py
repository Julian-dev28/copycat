"""discovery.public: the only surface other services should import.

    start_run(settings, sim_equity_usd, top_n, ..., mode="thread") -> run_id
    get_run(run_id) -> DiscoveryRun | None
    latest() -> DiscoveryRun | None
    create_run(...) -> run_id ; run_worker(run_id)    # for `python -m discovery worker`

Everything is backed by data/discovery.db, so any process can read a run
another process is executing.

mode="thread" runs in a daemon thread of the caller (CLI, tests, or the
api's own child process). mode="subprocess" launches
`python -m discovery worker --run-id <id>` detached, so the run survives
and never shares a GIL with the caller.

HL budget: every run switches this process's hl limiter to the
"background" priority class, which leaves a reserve of the shared per-IP
budget for the live engine.

One run at a time: an in-process lock plus the db's `running` rows. A
`running` row whose heartbeat is older than config.STALE_RUN_S belongs to a
dead worker and is marked failed instead of blocking forever.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from contracts.models import DiscoveryRun, Settings, TraderScore

from . import config, db, runner

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _conn() -> sqlite3.Connection:
    return db.connect(config.DB_PATH)


def _default_venue() -> Any:
    from hl import HlVenue   # lazy: discovery must not hard-depend on services/hl at import time
    return HlVenue()


def use_background_priority() -> None:
    """Draw from the shared HL budget as a background caller. No-op when hl
    isn't importable (fakes in tests)."""
    os.environ["COPYCAT_HL_PRIORITY"] = "background"
    try:
        from hl import rate_limit
    except ImportError:
        return
    if getattr(getattr(rate_limit, "HL_LIMITER", None), "priority", None) != "background":
        rate_limit.set_priority("background")


def _reap_stale(conn: sqlite3.Connection, now_ms: int) -> None:
    for row in db.running_rows(conn):
        hb = row.get("heartbeat_ms") or row["started_ms"]
        if now_ms - hb > config.STALE_RUN_S * 1000:
            db.update_run(conn, row["run_id"], status="failed", finished_ms=now_ms,
                          error=f"worker stopped heartbeating for {(now_ms - hb) / 1000:.0f}s")


def create_run(settings: Settings, sim_equity_usd: float, top_n: int = config.DEFAULT_TOP_N,
               opts: Optional[runner.RunOptions] = None) -> str:
    """Insert a `running` row (raises RuntimeError if one is live) without executing it."""
    conn = _conn()
    now_ms = int(time.time() * 1000)
    _reap_stale(conn, now_ms)
    row = conn.execute("SELECT run_id FROM runs WHERE status = 'running' LIMIT 1").fetchone()
    if row is not None:
        raise RuntimeError(f"a discovery run is already in progress (run_id={row['run_id']})")
    run_id = uuid.uuid4().hex
    db.create_run(conn, run_id, now_ms, sim_equity_usd, top_n, settings.model_dump_json(),
                  (opts or runner.RunOptions()).to_json())
    return run_id


def run_worker(run_id: str, venue: Optional[Any] = None, sizing_module: Optional[Any] = None) -> None:
    """Execute an already-created run synchronously in this thread."""
    use_background_priority()
    conn = _conn()
    row = db.get_run_row(conn, run_id)
    if row is None:
        raise KeyError(f"no such run: {run_id}")
    try:
        runner.execute(conn, venue if venue is not None else _default_venue(), run_id,
                       Settings.model_validate(json.loads(row["sim_settings_json"])), row["sim_equity_usd"],
                       row["top_n"], runner.RunOptions.from_json(row.get("params_json")),
                       sizing_module=sizing_module, db_path=config.DB_PATH)
    except Exception as exc:   # surface as a failed run, never a forever-running row
        logger.error("discovery run %s crashed: %s", run_id, exc, exc_info=True)
        db.update_run(conn, run_id, status="failed", finished_ms=int(time.time() * 1000), error=str(exc))


def start_run(
    settings: Settings,
    sim_equity_usd: float,
    top_n: int = config.DEFAULT_TOP_N,
    venue: Optional[Any] = None,
    window_days: int = config.DEFAULT_WINDOW_DAYS,
    min_account_value_usd: float = config.DEFAULT_MIN_ACCOUNT_VALUE_USD,
    min_volume_30d_usd: float = config.DEFAULT_MIN_VOLUME_30D_USD,
    include_hft: bool = False,
    mode: str = "thread",
    sizing_module: Optional[Any] = None,
) -> str:
    global _thread
    opts = runner.RunOptions(window_days=window_days, min_account_value_usd=min_account_value_usd,
                             min_volume_30d_usd=min_volume_30d_usd, include_hft=include_hft)
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("a discovery run is already in progress (this process)")
        run_id = create_run(settings, sim_equity_usd, top_n, opts)
        if mode == "subprocess":
            env = dict(os.environ, COPYCAT_HL_PRIORITY="background",
                       COPYCAT_DATA_DIR=str(Path(config.DB_PATH).parent))
            env.pop("COPYCAT_AGENT_KEY", None)   # discovery never signs anything
            subprocess.Popen([sys.executable, "-m", "discovery", "worker", "--run-id", run_id], env=env,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            return run_id
        venue_obj = venue if venue is not None else _default_venue()
        _thread = threading.Thread(target=run_worker, args=(run_id, venue_obj, sizing_module),
                                   name=f"discovery-run-{run_id[:8]}", daemon=True)
        _thread.start()
        return run_id


def _to_discovery_run(row: dict, results_raw: list) -> DiscoveryRun:
    return DiscoveryRun(
        run_id=row["run_id"], started_ms=row["started_ms"], finished_ms=row["finished_ms"],
        status=row["status"], sim_equity_usd=row["sim_equity_usd"],
        sim_settings=Settings.model_validate(json.loads(row["sim_settings_json"])),
        candidates=row["candidates"], scored=row["scored"], error=row["error"],
        results=[TraderScore.model_validate(r) for r in results_raw],
    )


def get_run(run_id: str) -> Optional[DiscoveryRun]:
    conn = _conn()
    row = db.get_run_row(conn, run_id)
    if row is None:
        return None
    return _to_discovery_run(row, db.get_results(conn, run_id))


def heartbeat_ms(run_id: str) -> Optional[int]:
    row = db.get_run_row(_conn(), run_id)
    return (row or {}).get("heartbeat_ms")


def latest() -> Optional[DiscoveryRun]:
    run_id = db.latest_run_id(_conn())
    return get_run(run_id) if run_id else None
