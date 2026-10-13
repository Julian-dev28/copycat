"""Version-skew guard (audit M12): is every long-running process on the
api's code?

The api, engine and `scout serve` each record their build at start
(contracts.build). After a pull or an edit, a process that was not restarted
keeps running old code: the api's previews, what-ifs and MCP plans can then
disagree with what the engine does, silently. GET /api/health returns every
component's build plus `stale`: the components to restart. The web shows a
banner while it is non-empty.

Rules, per component (engine, scout):
  - not running (no recent heartbeat): ignored; nothing to restart.
  - running with no recorded build: it started on code older than this
    guard, so it is stale ("unknown").
  - running with a different build id or contract version than the api: stale.
The api itself is compared against nothing: it IS the reference, and the
web compares its own contract version with the api's.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schemas import ComponentBuild


def component(name: str, build: Optional[Dict[str, Any]], alive: bool) -> ComponentBuild:
    b = build or {}
    return ComponentBuild(component=name, build=b.get("build"), contract_version=b.get("contract_version"),
                          started_ms=b.get("started_ms"), alive=alive)


def stale(api: ComponentBuild, others: List[ComponentBuild]) -> List[str]:
    out: List[str] = []
    for c in others:
        if not c.alive:
            continue
        if c.build is None or c.build != api.build or c.contract_version != api.contract_version:
            out.append(c.component)
    return out
