"""Agent status from HL's extraAgents, cached per main address for 10 minutes.

  no agent stored                         -> missing
  extraAgents read failed                 -> unknown (stored validUntil kept)
  agent not listed, stored validUntil past-> expired
  agent not listed otherwise              -> missing (revoked or replaced)
  listed, validUntil <= now               -> expired
  listed, validUntil <= now + 30 days     -> expiring
  listed                                  -> active

A failed read is cached for 30 s only, so a blip does not stick for 10 minutes.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from contracts.models import AgentStatus

from . import hlops

CACHE_TTL_S = 600.0
FAIL_TTL_S = 30.0
EXPIRING_MS = 30 * 24 * 3600 * 1000

_cache: Dict[str, Tuple[float, Optional[List[Dict[str, Any]]]]] = {}
_lock = threading.Lock()
_clock = time.monotonic


def lookup(main_address: str, force: bool = False) -> Optional[List[Dict[str, Any]]]:
    key = main_address.lower()
    now = _clock()
    with _lock:
        hit = _cache.get(key)
    if hit and not force:
        ts, rows = hit
        if now - ts < (CACHE_TTL_S if rows is not None else FAIL_TTL_S):
            return rows
    rows = hlops.extra_agents(key)
    with _lock:
        _cache[key] = (now, rows)
    return rows


def invalidate(main_address: Optional[str] = None) -> None:
    with _lock:
        if main_address is None:
            _cache.clear()
        else:
            _cache.pop(main_address.lower(), None)


def find_agent(rows: List[Dict[str, Any]], agent_address: str) -> Optional[Dict[str, Any]]:
    a = agent_address.lower()
    return next((r for r in rows if r.get("address") == a), None)


def classify(agent_address: Optional[str], rows: Optional[List[Dict[str, Any]]],
             stored_valid_until: Optional[int], now_ms: int) -> Tuple[AgentStatus, Optional[int]]:
    """(status, validUntil to store)."""
    if not agent_address:
        return AgentStatus.missing, None
    if rows is None:
        return AgentStatus.unknown, stored_valid_until
    hit = find_agent(rows, agent_address)
    if hit is None:
        if stored_valid_until is not None and stored_valid_until <= now_ms:
            return AgentStatus.expired, stored_valid_until
        return AgentStatus.missing, stored_valid_until
    vu = hit.get("validUntil")
    if vu is None:
        return AgentStatus.active, None
    if vu <= now_ms:
        return AgentStatus.expired, vu
    if vu - now_ms <= EXPIRING_MS:
        return AgentStatus.expiring, vu
    return AgentStatus.active, vu
