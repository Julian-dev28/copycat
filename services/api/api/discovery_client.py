"""Adapter in front of services/discovery's public surface
(`discovery.public`), imported lazily so the api works (with 503s on these
routes) even when services/discovery is not importable.

Runs execute in a SEPARATE PROCESS, not in the api. A discovery run is
minutes of CPU-heavy simulation plus hundreds of HL reads; inside the api it
shared the GIL with POST /api/engine/halt and /api/engine/close-all (the
kill switches) and spent from the api's HL rate budget. The child:
  - sets COPYCAT_HL_PRIORITY=background before `hl` is imported, so its
    reads only take HL rate tokens while the engine's reserve stays intact
    (services/hl/hl/rate_limit.py)
  - drops COPYCAT_AGENT_KEY (it never signs)
  - calls `discovery.public.start_run`, sends the run_id (or the error)
    back over a pipe, then polls `get_run` until the run leaves "running",
    because discovery's worker thread is a daemon and would die with the
    child otherwise.
The api reads progress and results with `get_run` / `latest`, straight from
data/discovery.db, in its own process: reads are cheap.
"""
from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from typing import Any, Optional, Protocol, Tuple

from contracts.models import DiscoveryRun, Settings

_START_TIMEOUT_S = 30.0
_POLL_S = 2.0


class DiscoveryUnavailable(RuntimeError):
    """discovery.public isn't importable, or the run process failed to start."""


class DiscoveryBusy(RuntimeError):
    """A discovery run is already in progress. Routes map this to 409."""


class DiscoveryClient(Protocol):
    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str: ...

    def get_run(self, run_id: str) -> Optional[DiscoveryRun]: ...

    def latest(self) -> Optional[DiscoveryRun]: ...


def run_child(conn: Any, settings_json: str, sim_equity_usd: float, top_n: int,
              data_dir: str, poll_s: float = _POLL_S) -> None:
    """Entry point of the discovery process (module level so `spawn` can
    import it). Sends exactly one message: ("ok", run_id) | ("busy", msg) |
    ("unavailable", msg) | ("error", msg)."""
    os.environ["COPYCAT_HL_PRIORITY"] = "background"
    os.environ["COPYCAT_DATA_DIR"] = data_dir
    os.environ.pop("COPYCAT_AGENT_KEY", None)
    try:
        from discovery import public  # type: ignore[import-not-found]
    except ImportError as e:
        conn.send(("unavailable", f"services/discovery isn't importable: {e}"))
        return
    try:
        run_id = public.start_run(Settings.model_validate_json(settings_json), sim_equity_usd, top_n)
    except RuntimeError as e:
        conn.send(("busy", str(e)))
        return
    except Exception as e:  # noqa: BLE001 -- anything else is reported, never swallowed
        conn.send(("error", f"{type(e).__name__}: {e}"))
        return
    conn.send(("ok", run_id))
    while True:
        run = public.get_run(run_id)
        if run is None or run.status != "running":
            return
        time.sleep(poll_s)


class RealDiscoveryClient:
    def __init__(self, data_dir: Path = Path("./data")):
        self.data_dir = Path(data_dir)

    @staticmethod
    def _public():
        try:
            from discovery import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise DiscoveryUnavailable(f"services/discovery isn't importable yet: {e}") from e
        return public

    def _spawn(self, settings_json: str, sim_equity_usd: float, top_n: int) -> Tuple[str, str]:
        multiprocessing.active_children()          # reap finished run processes
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=run_child, name="copycat-discovery",
                           args=(child, settings_json, sim_equity_usd, top_n, str(self.data_dir)))
        proc.start()
        child.close()
        if not parent.poll(_START_TIMEOUT_S):
            proc.kill()
            raise DiscoveryUnavailable("discovery process did not report a run id in time")
        try:
            return parent.recv()
        except EOFError as e:
            raise DiscoveryUnavailable("discovery process exited before starting a run") from e

    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str:
        kind, value = self._spawn(settings.model_dump_json(), sim_equity_usd, top_n)
        if kind == "ok":
            return value
        if kind == "busy":
            raise DiscoveryBusy(value)
        raise DiscoveryUnavailable(value)

    def get_run(self, run_id: str) -> Optional[DiscoveryRun]:
        return self._public().get_run(run_id)

    def latest(self) -> Optional[DiscoveryRun]:
        return self._public().latest()
