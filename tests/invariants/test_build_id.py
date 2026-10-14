"""contracts.build: a process's build id is the content of the packages it can
import, not the git commit.

Outcome this pins: a commit that touches only the web, docs, tests or a
package a process never imports leaves that process's id alone, so
GET /api/health `stale` no longer asks for an engine restart (it trades)
after a Scout or web change. The IMPORTS table is what makes that honest:
the first test scans the sources and fails the moment a new cross-package
import appears that the table does not list.
"""
from __future__ import annotations

import hashlib
import re

import pytest

from contracts import build as B

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(" + "|".join(B.PACKAGES) + r")(?=[.\s]|$)", re.M)


def scanned_imports(package: str) -> set:
    found = set()
    for p in (B.ROOT / B.PACKAGES[package]).rglob("*.py"):
        if any(part in B.EXCLUDED_PARTS for part in p.parts):
            continue
        found |= set(IMPORT_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
    found.discard(package)
    return found


def test_imports_table_matches_the_sources():
    scanned = {p: scanned_imports(p) for p in B.PACKAGES}
    assert scanned == B.IMPORTS, "contracts/build.py IMPORTS drifted from the sources"


def test_every_package_dir_is_a_package_and_every_component_has_one():
    for name, d in B.PACKAGES.items():
        assert (B.ROOT / d / "__init__.py").is_file(), (name, d)
    assert set(B.COMPONENTS.values()) <= set(B.PACKAGES)


def test_closures():
    assert B.closure("contracts") == ["contracts"]
    assert B.closure("engine") == ["contracts", "engine", "hl", "vault"]
    assert B.closure("discovery") == ["contracts", "discovery", "engine", "hl", "vault"]
    assert B.closure("api") == ["api", "contracts", "discovery", "engine", "hl", "vault"]
    assert B.closure("copycat_mcp") == ["contracts", "copycat_mcp"]
    assert B.component_dirs("nope") == []


def test_ids_on_this_checkout_are_per_component_and_deterministic():
    ids = B.compute_build_ids()
    assert set(ids) == set(B.COMPONENTS)
    assert all(re.fullmatch(r"[0-9a-f]{12}", v) for v in ids.values()), ids
    assert ids["scout"] == ids["discovery_worker"]                 # same entry package
    assert len({ids["api"], ids["engine"], ids["scout"], ids["mcp"]}) == 4
    assert B.compute_build_ids() == ids


# ── pure mapping: which edit moves which component ───────────────────────────

def _table(*paths: str) -> dict:
    return {p: hashlib.sha1(p.encode()).hexdigest() for p in paths}


BASE = _table("contracts/models.py", "contracts/build.py", "services/hl/hl/venue.py", "services/vault/vault/public.py",
              "services/engine/engine/core.py", "services/discovery/discovery/scout/refresh.py",
              "services/api/api/main.py", "services/mcp/copycat_mcp/server.py")


def moved_by(path: str, content: str = "edited") -> list:
    t = dict(BASE)
    t[path] = hashlib.sha1(content.encode()).hexdigest()
    before, after = B.ids_from_table(BASE), B.ids_from_table(t)
    return sorted(c for c in before if before[c] != after[c])


@pytest.mark.parametrize("path, expect", [
    ("services/web/src/app/page.tsx", []),
    ("docs/ARCHITECTURE.md", []),
    ("README.md", []),
    ("services/discovery/discovery/scout/README.md", []),           # a README inside a package
    ("services/engine/tests/test_core.py", []),
    ("services/discovery/evals/custom_wallet_check.py", []),
    ("services/engine/engine/__pycache__/core.cpython-312.pyc", []),
    ("services/engine/engine/.DS_Store", []),
    ("services/discovery/discovery/scout/rows.py", ["api", "discovery_worker", "scout"]),
    ("services/engine/engine/sizing.py", ["api", "discovery_worker", "engine", "scout"]),
    ("services/api/api/routes/health.py", ["api"]),
    ("services/mcp/copycat_mcp/server.py", ["mcp"]),
    ("contracts/models.py", ["api", "discovery_worker", "engine", "mcp", "scout"]),
    ("services/hl/hl/venue.py", ["api", "discovery_worker", "engine", "scout"]),   # the mcp talks HTTP only
    ("services/vault/vault/crypto.py", ["api", "discovery_worker", "engine", "scout"]),
    ("services/engine/engine/new_module.py", ["api", "discovery_worker", "engine", "scout"]),   # an added file
])
def test_which_components_an_edit_moves(path, expect):
    assert moved_by(path) == expect


def test_a_removed_file_moves_the_id():
    t = dict(BASE)
    del t["services/engine/engine/core.py"]
    before, after = B.ids_from_table(BASE), B.ids_from_table(t)
    assert sorted(c for c in before if before[c] != after[c]) == ["api", "discovery_worker", "engine", "scout"]


def test_unknown_when_a_component_has_nothing_on_disk():
    assert B.ids_from_table({}) == {c: B.UNKNOWN for c in B.COMPONENTS}
    only_mcp = _table("services/mcp/copycat_mcp/server.py")
    ids = B.ids_from_table(only_mcp)
    assert ids["mcp"] != B.UNKNOWN and ids["engine"] == B.UNKNOWN


def test_env_build_id_applies_to_every_component(monkeypatch):
    monkeypatch.setenv("COPYCAT_BUILD_ID", "img-2026-10-14")
    assert B.compute_build_ids() == {c: "img-2026-10-14" for c in B.COMPONENTS}


def test_included_rules():
    assert B.included("services/engine/engine/core.py")
    assert B.included("contracts/schema.json")
    assert not B.included("services/engine/engine/README.md")
    assert not B.included("services/engine/engine/tests/x.py")
    assert not B.included("services/engine/engine/__pycache__/x.pyc")
    assert not B.included("services/engine/engine/.hidden")


def test_record_uses_the_components_own_id(monkeypatch):
    monkeypatch.setattr(B, "_ids", None)
    monkeypatch.setattr(B, "_cache", {})
    monkeypatch.setattr(B, "compute_build_ids", lambda: {"engine": "e" * 12, "api": "a" * 12})
    assert B.record("engine", now_ms=5)["build"] == "e" * 12
    assert B.record("api")["build"] == "a" * 12
    assert B.record("engine", now_ms=9)["started_ms"] == 5      # first call wins
    assert B.build_id("scout") == B.UNKNOWN


def test_checkout_ids_are_cached_per_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(B, "_checkout", {"ids": None, "at": 0.0})
    monkeypatch.setattr(B, "compute_build_ids", lambda: calls.append(1) or {"engine": "x" * 12})
    assert B.checkout_build_id("engine", now=100.0) == "x" * 12
    assert B.checkout_build_id("engine", now=100.0 + B.CHECKOUT_TTL_S) == "x" * 12
    assert len(calls) == 1
    assert B.checkout_build_id("api", now=100.0 + B.CHECKOUT_TTL_S + 1) == B.UNKNOWN
    assert len(calls) == 2
