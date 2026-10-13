"""`make dev WEB_PORT=...` must keep the api's CORS allowlist in sync.

The api only accepts a browser Origin equal to COPYCAT_WEB_ORIGIN (default
http://localhost:3000, services/api/api/config.py DEFAULT_WEB_ORIGIN). Before
this test, overriding WEB_PORT without also hand-editing .env's
COPYCAT_WEB_ORIGIN made every authenticated request fail CORS preflight with
a generic "can't reach the api" in the web, no hint that the port was the
cause (reproduced live: POST /api/accounts/create got a 400 "Disallowed CORS
origin" on the OPTIONS preflight). The Makefile now derives
COPYCAT_WEB_ORIGIN from WEB_PORT automatically, but only when WEB_PORT was
actually passed on the command line, so plain `make dev` and a custom
COPYCAT_WEB_ORIGIN already in .env are both left alone.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _make_db(*args: str) -> str:
    """`make -p`'s variable database, without running any recipe."""
    out = subprocess.run(
        ["make", "-p", *args], cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def _origin_value(db: str) -> str | None:
    m = re.search(r"^COPYCAT_WEB_ORIGIN\s*:?=\s*(\S+)", db, re.MULTILINE)
    return m.group(1) if m else None


def test_default_make_dev_leaves_web_origin_unset():
    # No WEB_PORT override: don't export anything, so .env's COPYCAT_WEB_ORIGIN
    # (or the api's own DEFAULT_WEB_ORIGIN) still decides.
    assert _origin_value(_make_db()) is None


def test_custom_web_port_derives_a_matching_origin():
    db = _make_db("WEB_PORT=3205")
    assert _origin_value(db) == "http://localhost:3205"


def test_default_web_port_also_derives_the_documented_default():
    # Passed explicitly but equal to the default: still exported (the api's
    # own default happens to match, so this is a no-op in practice).
    db = _make_db("WEB_PORT=3000")
    assert _origin_value(db) == "http://localhost:3000"
