"""Adapter in front of the Scout surface (`discovery.scout.public`),
imported lazily so the api works (with 503s on the Scout routes) even when
that package is missing or mid-build. Routes depend on the `ScoutClient`
Protocol; tests inject tests/api_fakes.FakeScoutClient and never import
`discovery`.

Where Scout work runs:
  - The heavy part (leaderboard pull, per-wallet stats, sims, building
    `scout_rows`) runs in its own process, `python -m discovery.scout serve`
    (Makefile `dev`, docker-compose `scout`), at COPYCAT_HL_PRIORITY=
    background and without the agent key. The api never builds the board.
  - The api only READS: one indexed SQL query on `scout_rows` for the list,
    a stored blob for the profile, a cached page of fills. Those are cheap,
    so they run in this process, on FastAPI's threadpool (every Scout route
    is a sync `def`, which FastAPI runs via `run_in_threadpool`). They never
    block the event loop that serves /api/engine/halt and close-all, and a
    spawn-per-request child would cost more in interpreter start-up (~1 s)
    than the read itself (target p95 < 50 ms, spec section 7.3).
  - what-if is one wallet's sim on cached fills and candles: CPU-bound but
    bounded (seconds, not minutes), and 1-concurrent (api.routes.scout holds
    a non-blocking lock, a second request is 409). It also runs on the
    threadpool. While it runs it shares the GIL with the kill-switch
    routes, but those are a few-ms settings write each and CPython hands
    the GIL over every 5 ms (sys.getswitchinterval), so they are delayed by
    milliseconds, never queued behind the sim. A discovery RUN (minutes,
    hundreds of wallets) is the case that justified a subprocess; one
    wallet is not.
  - The few live HL reads the Scout surface may make from this process
    (open orders, weight 20; a stale positions refresh, weight 2/dex) must
    not spend the engine's reserve, so the first real call flips this
    process to COPYCAT_HL_PRIORITY=background. The api makes no other HL
    calls (discovery runs are in their own child), and `hl.rate_limit`
    reads the variable on every acquire, so the flip takes effect even if
    `hl` was imported earlier.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Protocol, Union

from contracts.models import (
    LeaderFillView,
    LeaderOverride,
    OpenOrderView,
    ScoutPresets,
    ScoutStatus,
    Settings,
    TraderPage,
    TraderProfile,
    WhatIfResult,
)


class ScoutUnavailable(RuntimeError):
    """discovery.scout.public isn't importable. Routes map this to 503."""


class ScoutBusy(RuntimeError):
    """A refresh (or a what-if) is already running. Routes map this to 409."""


class ScoutClient(Protocol):
    def page(self, query: Dict[str, Any]) -> TraderPage: ...

    def profile(self, address: str) -> Union[TraderProfile, ScoutStatus, None]: ...

    def fills(self, address: str, before_ms: Optional[int], limit: int) -> List[LeaderFillView]: ...

    def orders(self, address: str) -> List[OpenOrderView]: ...

    def what_if(self, address: str, settings: Settings, sim_equity_usd: float,
                override: LeaderOverride) -> WhatIfResult: ...

    def presets(self) -> ScoutPresets: ...

    def status(self) -> ScoutStatus: ...

    def refresh(self) -> ScoutStatus: ...


def _plain(v: Any) -> Any:
    """Pydantic model -> dict, recursively through lists; anything else as is."""
    if hasattr(v, "model_dump"):
        return v.model_dump(mode="json")
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def open_order_view(o: Any) -> OpenOrderView:
    """OpenOrderView from either an OpenOrderView-shaped dict/model or a raw
    HL `frontendOpenOrders` / `openOrders` row (camelCase, numbers as
    strings), so the route is typed whichever discovery hands back."""
    d = _plain(o)
    if "limitPx" not in d:
        return OpenOrderView.model_validate(d)
    px, sz = float(d["limitPx"]), float(d["sz"])
    trig = d.get("triggerPx")
    return OpenOrderView(
        oid=int(d["oid"]), coin=d["coin"], side=d["side"],
        order_type=d.get("orderType") or "Limit", limit_px=px, sz=sz,
        orig_sz=float(d.get("origSz", sz)), notional_usd=px * sz,
        reduce_only=bool(d.get("reduceOnly", False)), is_trigger=bool(d.get("isTrigger", False)),
        trigger_px=float(trig) if trig not in (None, "", "0", "0.0") else None,
        trigger_condition=d.get("triggerCondition") if d.get("triggerCondition") not in (None, "N/A") else None,
        tif=d.get("tif"), time_ms=int(d["timestamp"]),
    )


class RealScoutClient:
    @staticmethod
    def _public() -> Any:
        try:
            from discovery.scout import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise ScoutUnavailable(f"discovery.scout isn't importable yet: {e}") from e
        os.environ["COPYCAT_HL_PRIORITY"] = "background"   # see module docstring
        return public

    def _call(self, name: str, *args: Any) -> Any:
        public = self._public()
        fn = getattr(public, name, None)
        if fn is None:
            raise ScoutUnavailable(f"discovery.scout.public has no {name}() yet")
        busy = getattr(public, "ScoutBusy", None)
        try:
            return fn(*args)
        except Exception as e:
            if isinstance(busy, type) and isinstance(e, busy):
                raise ScoutBusy(str(e)) from e
            raise

    def page(self, query: Dict[str, Any]) -> TraderPage:
        return TraderPage.model_validate(_plain(self._call("scout_page", query)))

    def profile(self, address: str) -> Union[TraderProfile, ScoutStatus, None]:
        out = self._call("scout_profile", address)
        if out is None or isinstance(out, (TraderProfile, ScoutStatus)):
            return out
        data = _plain(out)
        if isinstance(data, dict) and "row" in data:
            return TraderProfile.model_validate(data)
        return ScoutStatus.model_validate(data)

    def fills(self, address: str, before_ms: Optional[int], limit: int) -> List[LeaderFillView]:
        return [LeaderFillView.model_validate(_plain(f))
                for f in self._call("scout_fills", address, before_ms, limit)]

    def orders(self, address: str) -> List[OpenOrderView]:
        return [open_order_view(o) for o in self._call("scout_orders", address)]

    def what_if(self, address: str, settings: Settings, sim_equity_usd: float,
                override: LeaderOverride) -> WhatIfResult:
        return WhatIfResult.model_validate(
            _plain(self._call("scout_what_if", address, settings, sim_equity_usd, override)))

    def presets(self) -> ScoutPresets:
        return ScoutPresets.model_validate(_plain(self._call("scout_presets")))

    def status(self) -> ScoutStatus:
        return ScoutStatus.model_validate(_plain(self._call("scout_status")))

    def refresh(self) -> ScoutStatus:
        return ScoutStatus.model_validate(_plain(self._call("scout_refresh")))
