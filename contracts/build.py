"""Build identity of a running Python process (version-skew guard).

Every long-running process (api, engine, scout serve, discovery worker,
mcp) calls `record(component)` once at start. The api returns every
component's build in GET /api/health and the web shows a banner when one
differs from the api's, so a process still running older code is visible,
never silent. (The bug that motivated it: the api ran an old copy-sim while
the web had hot-reloaded new code; a 1x what-if showed the saved settings'
result. No test failed.)

build id:
  COPYCAT_BUILD_ID when set (docker images bake it in), else
  `git rev-parse --short HEAD`, plus "+<6 hex>" when the Python sources
  (contracts/, services/ minus the web) differ from HEAD: a hash of
  `git diff HEAD` and the untracked .py files. Two processes started from the
  same commit but on either side of an uncommitted edit get different ids.
  "unknown" when git is unavailable.

Pure stdlib, computed once per process (the result is cached).
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .models import CONTRACT_VERSION

ROOT = Path(__file__).resolve().parent.parent
PY_PATHS = ["contracts", "services", ":(exclude)services/web", ":(exclude,glob)**/*.md", ":(exclude,glob)**/tests/**"]

_cache: Dict[str, Dict[str, Any]] = {}
_build_id: Optional[str] = None
logger = logging.getLogger(__name__)


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def compute_build_id() -> str:
    env = os.environ.get("COPYCAT_BUILD_ID", "").strip()
    if env:
        return env
    head = (_git("rev-parse", "--short", "HEAD") or "").strip()
    if not head:
        return "unknown"
    diff = _git("diff", "HEAD", "--no-ext-diff", "--", *PY_PATHS) or ""
    untracked = (_git("ls-files", "--others", "--exclude-standard", "--", *PY_PATHS) or "").split()
    h = hashlib.sha1(diff.encode())
    for f in sorted(p for p in untracked if p.endswith(".py")):
        try:
            h.update(f.encode() + (ROOT / f).read_bytes())
        except OSError:
            continue
    if not diff and not any(p.endswith(".py") for p in untracked):
        return head
    return f"{head}+{h.hexdigest()[:6]}"


def build_id() -> str:
    global _build_id
    if _build_id is None:
        _build_id = compute_build_id()
    return _build_id


def record(component: str, now_ms: Optional[int] = None) -> Dict[str, Any]:
    """This process's build info for `component` (first call wins; logged once)."""
    if component not in _cache:
        _cache[component] = {"component": component, "build": build_id(), "contract_version": CONTRACT_VERSION,
                             "started_ms": int(now_ms if now_ms is not None else time.time() * 1000),
                             "pid": os.getpid()}
        logger.info("%s build %s (contract v%d)", component, _cache[component]["build"], CONTRACT_VERSION)
    return dict(_cache[component])


def get(component: str) -> Optional[Dict[str, Any]]:
    return dict(_cache[component]) if component in _cache else None
