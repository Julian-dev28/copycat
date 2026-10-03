"""HTTP layer: a shared keep-alive session, a forced read timeout, and
`http_post` -- the one function every read in this package goes through.

The timeout guard exists because of a real incident: hyperliquid-python-sdk's
`API.post` calls `self.session.request(..., timeout=self.timeout)`, and
`self.timeout` defaults to `None`. That `None` is passed EXPLICITLY, not
omitted -- so a naive `kw.setdefault("timeout", ...)` guard never fires (the
`timeout` key is always already present in `kw`). Only overwriting an
explicit `None` closes the hang. Without this, a dead socket blocks forever
(pathiel incident, 2026-07-10: a hung read froze a live monitor for 15
minutes; the bug was still live as of 2026-10-02 because an earlier guard
used `setdefault`).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

from . import env, rate_limit

# NOTE: deliberately `from . import rate_limit` and not
# `from .rate_limit import HL_LIMITER` -- the latter binds this module's own
# name to the object that existed at import time, so a test (or ops code)
# that does `monkeypatch.setattr(rate_limit, "HL_LIMITER", ...)` would
# silently not affect this module's calls. Going through the module keeps
# every caller looking up the current `HL_LIMITER` each time.

logger = logging.getLogger(__name__)


def set_session_timeout(client: Any, timeout_s: Optional[float] = None) -> Any:
    """Force a default read timeout onto an SDK client's `requests.Session`.

    Best-effort: if the SDK's internals change shape (no `.session`
    attribute, or `.session.request` is not a plain callable), the client
    still works, just unprotected -- logged loudly so that regression has a
    trace instead of silently reintroducing the hang this guard exists for.
    """
    if timeout_s is None:
        timeout_s = env.request_timeout_s()
    try:
        sess = getattr(client, "session", None)
        if sess is None:
            return client
        orig_request = sess.request

        def _request(method, url, **kw):
            # NOT setdefault: the SDK passes timeout=self.timeout explicitly
            # (and that default is None), so the key is always present and
            # setdefault would never fire. Must check the VALUE, not presence.
            if kw.get("timeout") is None:
                kw["timeout"] = timeout_s
            return orig_request(method, url, **kw)

        sess.request = _request
    except Exception as exc:
        logger.warning(f"[hl.http] could not install read timeout, client is UNPROTECTED against a hung read: {exc}")
    return client


_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


def get_session() -> requests.Session:
    """The shared connection-pooled session for our own direct /info and
    leaderboard calls. Retries 502/503/504 at the adapter level (2 attempts,
    0.3s backoff factor) -- transient HL-side 5xx, not our rate limiting."""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=16,
                    pool_maxsize=32,
                    max_retries=Retry(
                        total=2, backoff_factor=0.3,
                        status_forcelist=[502, 503, 504],
                        allowed_methods=["POST", "GET"],
                    ),
                )
                s.mount("https://", adapter)
                s.mount("http://", adapter)
                _session = s
    return _session


def reset_session() -> None:
    """Test hook: drop the cached session so a monkeypatched get_session
    (or a fresh base_url) starts clean."""
    global _session
    with _session_lock:
        _session = None


def http_post(
    path: str,
    payload: Dict[str, Any],
    timeout: Optional[float] = None,
    item_count: Optional[int] = None,
    max_wait: float = 30.0,
) -> Any:
    """POST `payload` to `{base_url}{path}` for the active network.

    Returns the parsed JSON body, or None on ANY failure: rate-budget
    exhaustion, a network timeout, an HTTP error status, or unparseable
    JSON. Every failure is logged; nothing here ever raises into the
    caller -- callers decide what "no data" means for their own contract
    (None for a whole read, 0.0 for a price, etc).
    """
    req_type = payload.get("type")
    weight = rate_limit.endpoint_weight(req_type, item_count)
    if not rate_limit.HL_LIMITER.acquire(weight, max_wait=max_wait):
        logger.warning(
            f"[hl.http] rate budget exhausted for {req_type or 'unknown'} "
            f"(weight={weight}, waited {max_wait:g}s) -- returning None"
        )
        return None
    if timeout is None:
        timeout = env.request_timeout_s()
    url = f"{env.base_url()}{path}"
    try:
        resp = get_session().post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error(f"[hl.http] POST {path} type={req_type!r} failed: {exc}")
        return None
