"""Build identity of a running Python process (version-skew guard).

Every long-running process (api, engine, scout serve, discovery worker,
mcp) calls `record(component)` once at start. The api returns every
component's build in GET /api/health next to the id of that component's
code on disk, and the web shows a strip when they differ, so a process
still running older code is visible, never silent. (The bug that motivated
it: the api ran an old copy-sim while the web had hot-reloaded new code; a
1x what-if showed the saved settings' result. No test failed.)

build id, per component:
  COPYCAT_BUILD_ID when set (docker images bake it in), else 12 hex of a
  sha1 over the content of every file the component's process can import:
  its entry package plus the repo packages that package imports,
  transitively (IMPORTS below; tests/invariants/test_build_id.py scans the
  sources and fails when the table drifts). Working-tree content, tracked
  or not, minus *.md, tests/ and __pycache__. So a commit that touches only
  the web, docs, tests or a package the component never imports leaves its
  id, and `stale` in GET /api/health, unchanged. Before this the id was the
  git commit and every commit flagged every running process, the engine
  included, for a restart it did not need. "unknown" when the component's
  packages are not on disk.

Pure stdlib. This process's own ids are computed once (cached); the on-disk
ids the api compares against are recomputed at most every CHECKOUT_TTL_S.
contracts/evals/build_skew_check.sh proves the edit-to-component mapping on
a throwaway git worktree.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .models import CONTRACT_VERSION

ROOT = Path(__file__).resolve().parent.parent

# importable name -> its directory, repo relative
PACKAGES: Dict[str, str] = {
    "contracts": "contracts",
    "hl": "services/hl/hl",
    "vault": "services/vault/vault",
    "engine": "services/engine/engine",
    "discovery": "services/discovery/discovery",
    "api": "services/api/api",
    "copycat_mcp": "services/mcp/copycat_mcp",
}
# package -> the repo packages its sources import, lazy in-function imports
# included (tests/invariants/test_build_id.py keeps this equal to the sources)
IMPORTS: Dict[str, Set[str]] = {
    "contracts": set(),
    "hl": {"vault"},
    "vault": {"contracts", "hl"},
    "engine": {"contracts", "hl", "vault"},
    "discovery": {"contracts", "hl", "engine"},
    "api": {"contracts", "hl", "vault", "engine", "discovery"},
    "copycat_mcp": {"contracts"},
}
# process name, as passed to record() -> its entry package
COMPONENTS: Dict[str, str] = {
    "api": "api",
    "engine": "engine",
    "scout": "discovery",
    "discovery_worker": "discovery",
    "mcp": "copycat_mcp",
}
EXCLUDED_SUFFIXES = (".md", ".pyc")
EXCLUDED_PARTS = ("tests", "__pycache__")
ID_HEX = 12
UNKNOWN = "unknown"

logger = logging.getLogger(__name__)


def closure(package: str) -> List[str]:
    """`package` plus everything it imports from the repo, transitively, sorted."""
    seen: Set[str] = set()
    todo = [package]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo.extend(IMPORTS.get(p, ()))
    return sorted(seen)


def component_dirs(component: str) -> List[str]:
    """The repo directories whose content is `component`'s build id."""
    entry = COMPONENTS.get(component)
    if entry is None:
        return []
    return [PACKAGES[p] for p in closure(entry)]


def included(path: str) -> bool:
    """Does this repo-relative file count toward a build id? Docs, tests,
    bytecode and dotfiles never do."""
    parts = path.split("/")
    if path.endswith(EXCLUDED_SUFFIXES):
        return False
    return not any(p in EXCLUDED_PARTS or p.startswith(".") for p in parts)


def _list_files(dirs: Iterable[str]) -> List[str]:
    """Every file under `dirs` on disk: tracked and untracked (not ignored)
    through git, or a plain walk when git is unavailable."""
    existing = [d for d in dirs if (ROOT / d).is_dir()]
    if not existing:
        return []
    files: List[str] = []
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *existing],
                             cwd=ROOT, capture_output=True, timeout=5, check=True).stdout
        files = [f for f in out.decode("utf-8", errors="replace").split("\0") if f]
    except (OSError, subprocess.SubprocessError):
        for d in existing:
            files.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / d).rglob("*") if p.is_file())
    return sorted({f for f in files if included(f)})


def file_table(dirs: Iterable[str]) -> Dict[str, str]:
    """{repo path: sha1 of its content} for the files under `dirs` now.
    A path listed by git but gone from disk (deleted, not yet staged) is
    simply absent, which moves the id like any other change."""
    table: Dict[str, str] = {}
    for f in _list_files(dirs):
        try:
            table[f] = hashlib.sha1((ROOT / f).read_bytes()).hexdigest()
        except OSError:
            continue
    return table


def ids_from_table(table: Dict[str, str]) -> Dict[str, str]:
    """component -> build id, from a file table. Pure: tests feed it a fake tree."""
    out: Dict[str, str] = {}
    for comp in COMPONENTS:
        prefixes = tuple(d + "/" for d in component_dirs(comp))
        lines = [f"{p} {h}" for p, h in sorted(table.items()) if included(p) and p.startswith(prefixes)]
        out[comp] = hashlib.sha1("\n".join(lines).encode()).hexdigest()[:ID_HEX] if lines else UNKNOWN
    return out


def compute_build_ids() -> Dict[str, str]:
    """Every component's build id from the code on disk right now."""
    env = os.environ.get("COPYCAT_BUILD_ID", "").strip()
    if env:
        return {c: env for c in COMPONENTS}
    return ids_from_table(file_table(sorted(set(PACKAGES.values()))))


_ids: Optional[Dict[str, str]] = None


def build_id(component: str) -> str:
    """The id of the code THIS process started with (computed once)."""
    global _ids
    if _ids is None:
        _ids = compute_build_ids()
    return _ids.get(component, UNKNOWN)


_checkout: Dict[str, Any] = {"ids": None, "at": 0.0}
CHECKOUT_TTL_S = 15.0


def checkout_build_id(component: str, now: Optional[float] = None) -> str:
    """The build id of `component`'s code ON DISK right now (recomputed at
    most every CHECKOUT_TTL_S), as opposed to `build_id()`, which is what
    THIS process started with. They differ after a pull or an edit of a file
    the component imports, until that process is restarted: that is the
    skew GET /api/health reports, per component."""
    t = time.time() if now is None else now
    if _checkout["ids"] is None or t - float(_checkout["at"]) > CHECKOUT_TTL_S:
        _checkout["ids"] = compute_build_ids()
        _checkout["at"] = t
    return str(_checkout["ids"].get(component, UNKNOWN))


_cache: Dict[str, Dict[str, Any]] = {}


def record(component: str, now_ms: Optional[int] = None) -> Dict[str, Any]:
    """This process's build info for `component` (first call wins; logged once)."""
    if component not in _cache:
        _cache[component] = {"component": component, "build": build_id(component), "contract_version": CONTRACT_VERSION,
                             "started_ms": int(now_ms if now_ms is not None else time.time() * 1000),
                             "pid": os.getpid()}
        logger.info("%s build %s (contract v%d)", component, _cache[component]["build"], CONTRACT_VERSION)
    return dict(_cache[component])


def get(component: str) -> Optional[Dict[str, Any]]:
    return dict(_cache[component]) if component in _cache else None
