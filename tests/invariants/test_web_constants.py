"""The web's hand-kept constants (services/web/src/lib/api/types.ts) match the
contracts. CONTRACT_VERSION drifted to 5 while the contracts were at 11 once;
the version-skew strip compares against it, so drift would be a false alarm
or a silent miss."""
from __future__ import annotations

import re
from pathlib import Path

from contracts import models

TYPES = Path(__file__).resolve().parents[2] / "services" / "web" / "src" / "lib" / "api" / "types.ts"


def _const(name: str) -> float:
    m = re.search(rf"export const {name} = ([0-9.]+);", TYPES.read_text())
    assert m, name
    return float(m.group(1))


def test_web_constants_match_the_contracts():
    assert _const("CONTRACT_VERSION") == models.CONTRACT_VERSION
    assert _const("MAX_LEADERS") == models.MAX_LEADERS
    assert _const("HL_MIN_ORDER_USD") == models.HL_MIN_ORDER_USD
    assert _const("MAX_LEVERAGE_CAP") == models.MAX_LEVERAGE_CAP


def test_web_unreliable_grace_matches_the_engine():
    import re as _re
    from engine.core import UNRELIABLE_GRACE_MS
    src = (TYPES.parents[1] / "engine" / "dayPnl.ts").read_text()
    m = _re.search(r"export const UNRELIABLE_GRACE_MS = ([0-9_ *]+);", src)
    assert m and eval(m.group(1).replace("_", "")) == UNRELIABLE_GRACE_MS
