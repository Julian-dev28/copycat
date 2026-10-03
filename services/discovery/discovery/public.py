"""discovery.public: the only surface other services should import.

    start_run(settings, sim_equity_usd, top_n) -> run_id   # runs in a background thread
    get_run(run_id) -> DiscoveryRun | None
    latest() -> DiscoveryRun | None

Only one run at a time, enforced two ways: an in-process lock (covers the
common case -- one api process, one CLI invocation) and a check against the
db's own `running` rows (covers a run started by a different process than
the one calling start_run next). A run that crashed mid-flight without
reaching `execute()`'s final `status="done"/"failed"` update leaves a
`running` row behind; recovering from that is an ops action (mark it
failed by hand), not something start_run silently papers over.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
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


def start_run(
    settings: Settings,
    sim_equity_usd: float,
    top_n: int = config.DEFAULT_TOP_N,
    venue: Optional[Any] = None,
    window_days: int = config.DEFAULT_WINDOW_DAYS,
    min_account_value_usd: float = config.DEFAULT_MIN_ACCOUNT_VALUE_USD,
    min_volume_30d_usd: float = config.DEFAULT_MIN_VOLUME_30D_USD,
) -> str:
    global _thread
    conn = _conn()
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("a discovery run is already in progress (this process)")
        row = conn.execute("SELECT run_id FROM runs WHERE status = 'running' LIMIT 1").fetchone()
        if row is not None:
            raise RuntimeError(f"a discovery run is already in progress (run_id={row['run_id']})")

        run_id = uuid.uuid4().hex
        venue_obj = venue if venue is not None else _default_venue()
        db.create_run(conn, run_id, int(time.time() * 1000), sim_equity_usd, top_n,
                       settings.model_dump_json())

        def _run() -> None:
            # each thread needs its own sqlite connection (see db.connect)
            try:
                runner.execute(db.connect(config.DB_PATH), venue_obj, run_id, settings,
                                sim_equity_usd, top_n, window_days, min_account_value_usd,
                                min_volume_30d_usd)
            except Exception as exc:   # the background thread has no other way to surface this
                logger.error("discovery run %s crashed: %s", run_id, exc, exc_info=True)
                try:
                    db.update_run(db.connect(config.DB_PATH), run_id, status="failed",
                                   finished_ms=int(time.time() * 1000), error=str(exc))
                except Exception:
                    logger.error("discovery run %s: failed to persist crash status", run_id, exc_info=True)

        _thread = threading.Thread(target=_run, name=f"discovery-run-{run_id[:8]}", daemon=True)
        _thread.start()
        return run_id


def _to_discovery_run(row: dict, results_raw: list) -> DiscoveryRun:
    results = [TraderScore.model_validate(r) for r in results_raw]
    return DiscoveryRun(
        run_id=row["run_id"],
        started_ms=row["started_ms"],
        finished_ms=row["finished_ms"],
        status=row["status"],
        sim_equity_usd=row["sim_equity_usd"],
        sim_settings=Settings.model_validate(json.loads(row["sim_settings_json"])),
        candidates=row["candidates"],
        scored=row["scored"],
        error=row["error"],
        results=results,
    )


def get_run(run_id: str) -> Optional[DiscoveryRun]:
    conn = _conn()
    row = db.get_run_row(conn, run_id)
    if row is None:
        return None
    results = db.get_results(conn, run_id)
    return _to_discovery_run(row, results)


def latest() -> Optional[DiscoveryRun]:
    conn = _conn()
    run_id = db.latest_run_id(conn)
    if run_id is None:
        return None
    return get_run(run_id)
