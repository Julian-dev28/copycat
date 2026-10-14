"""Adapter in front of `discovery.thesis.public`, imported lazily (503 on
the thesis routes when it isn't importable). Routes depend on the
`ThesisClient` Protocol; tests inject tests/api_fakes.FakeThesisClient.

    fingerprint(address, window_days=30, venue=None) -> StrategyFingerprint   SLOW
    ta_thesis(address) -> Thesis
    save_thesis(Thesis) -> None
    get_theses(address) -> List[Thesis]

`fingerprint` pulls up to 30 days of fills plus candles for every coin he
traded and replays them: seconds to minutes of HL reads and CPU. It never
runs in the api process. `RealThesisClient.fingerprint` spawns a child
(COPYCAT_HL_PRIORITY=background, absolute data dir, no agent key: the recipe
for every HL-reading child of the api) that computes the fingerprint, then the
"ta" thesis from it and saves that, and sends the fingerprint back over a
pipe. The caller of `fingerprint` is the single worker thread of
api.fingerprint_jobs, which only waits on the pipe, so the api's event loop
and threadpool never carry that work.

`get_theses` / `save_thesis` are single sqlite reads/writes: they run in the
api process, on the threadpool (sync routes).
"""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import Any, List, Protocol, Tuple

from contracts.models import StrategyFingerprint, Thesis

_FINGERPRINT_TIMEOUT_S = 900.0


class ThesisUnavailable(RuntimeError):
    """discovery.thesis.public isn't importable. Routes map this to 503."""


class FingerprintFailed(RuntimeError):
    """The fingerprint child failed or timed out. Routes map this to 502."""


class ThesisClient(Protocol):
    def fingerprint(self, address: str, window_days: int) -> StrategyFingerprint: ...

    def theses(self, address: str) -> List[Thesis]: ...

    def save(self, thesis: Thesis) -> None: ...


def fingerprint_child(conn: Any, address: str, window_days: int, data_dir: str) -> None:
    """Entry point of the fingerprint process (module level so `spawn` can
    import it). Sends exactly one message: ("ok", fingerprint_json) |
    ("unavailable", msg) | ("error", msg)."""
    os.environ["COPYCAT_HL_PRIORITY"] = "background"
    os.environ["COPYCAT_DATA_DIR"] = data_dir
    os.environ.pop("COPYCAT_AGENT_KEY", None)
    try:
        from discovery.thesis import public  # type: ignore[import-not-found]
    except ImportError as e:
        conn.send(("unavailable", f"discovery.thesis isn't importable: {e}"))
        return
    try:
        fp = public.fingerprint(address, window_days=window_days)
    except Exception as e:  # noqa: BLE001 -- reported to the api, never swallowed
        conn.send(("error", f"{type(e).__name__}: {e}"))
        return
    # Refresh the stored "ta" thesis while the fills and candles are warm.
    # A failure here must not lose the fingerprint, so it is only logged.
    try:
        public.save_thesis(public.ta_thesis(address))
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("ta thesis for %s failed: %s", address, e)
    conn.send(("ok", _plain(fp)))


def _plain(v: Any) -> Any:
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


class RealThesisClient:
    def __init__(self, data_dir: Path = Path("./data")):
        self.data_dir = Path(data_dir).resolve()

    @staticmethod
    def _public() -> Any:
        try:
            from discovery.thesis import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise ThesisUnavailable(f"discovery.thesis isn't importable yet: {e}") from e
        return public

    def _spawn(self, address: str, window_days: int) -> Tuple[str, Any]:
        multiprocessing.active_children()          # reap finished children
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=fingerprint_child, name="copycat-fingerprint",
                           args=(child, address, window_days, str(self.data_dir)))
        proc.start()
        child.close()
        try:
            if not parent.poll(_FINGERPRINT_TIMEOUT_S):
                proc.kill()
                raise FingerprintFailed(f"fingerprint for {address} timed out after "
                                        f"{_FINGERPRINT_TIMEOUT_S:.0f}s")
            try:
                return parent.recv()
            except EOFError as e:
                raise FingerprintFailed("fingerprint process exited without a result") from e
        finally:
            proc.join(timeout=5)

    def fingerprint(self, address: str, window_days: int) -> StrategyFingerprint:
        kind, value = self._spawn(address, window_days)
        if kind == "ok":
            return StrategyFingerprint.model_validate(value)
        if kind == "unavailable":
            raise ThesisUnavailable(value)
        raise FingerprintFailed(value)

    def theses(self, address: str) -> List[Thesis]:
        return [Thesis.model_validate(_plain(t)) for t in self._public().get_theses(address)]

    def save(self, thesis: Thesis) -> None:
        self._public().save_thesis(thesis)
