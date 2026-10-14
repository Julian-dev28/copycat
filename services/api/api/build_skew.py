"""Version-skew guard (audit M12): is every long-running process on the
code that is on disk for it?

The api, engine and `scout serve` each record their build at start
(contracts.build: a content hash of the packages that process imports).
After a pull or an edit, a process that was not restarted keeps running old
code: the api's previews, what-ifs and MCP plans can then disagree with
what the engine does, silently. GET /api/health returns every component's
build next to the id of its code on disk (`checkout`), plus `stale`: the
components to restart. The web shows a strip while it is non-empty.

Rules, per component (api, engine, scout):
  - not running (no recent heartbeat): ignored; nothing to restart.
  - running with no recorded build: it started on code older than this
    guard, so it is stale ("unknown").
  - running on a different contract version than the api: stale.
  - running with a build id other than its own code on disk: stale. When
    the on-disk id is unknown (no packages on disk) the build is not judged:
    never a false alarm. Each component is compared with ITS OWN packages,
    so a commit that touches only the web, docs or a service the engine never
    imports does not flag the engine.
The web compares its own contract version with the api's.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts.build import UNKNOWN

from .schemas import ComponentBuild


def known(build_id: Optional[str]) -> Optional[str]:
    return build_id if build_id and build_id != UNKNOWN else None


def component(name: str, build: Optional[Dict[str, Any]], alive: bool, checkout: Optional[str] = None) -> ComponentBuild:
    b = build or {}
    return ComponentBuild(component=name, build=b.get("build"), contract_version=b.get("contract_version"),
                          started_ms=b.get("started_ms"), alive=alive, checkout=known(checkout))


def stale(api: ComponentBuild, others: List[ComponentBuild]) -> List[str]:
    """Components to restart: each one against its own code on disk."""
    out: List[str] = []
    if api.build and api.checkout and api.build != api.checkout:
        out.append("api")
    for c in others:
        if not c.alive:
            continue
        if c.build is None or c.contract_version != api.contract_version or (c.checkout and c.build != c.checkout):
            out.append(c.component)
    return out
