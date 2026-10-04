"""Live eval, not a gate test (excluded by the default `-m 'not live'`).
Fingerprints three real leaders through hl.HlVenue (read-only, background
priority) into a temp db, and checks the output is usable.

    .venv/bin/python -m pytest services/discovery/tests/test_thesis_live.py -m live -s

Pass criteria per leader: no exception; trips_analyzed > 0; 4 to 8
summary sentences (1 when there are no trips); no em/en dashes; every
tag comes from config.TAG_RULES; 1..8 unique examples; recomputing the
text from the same fingerprint is identical; at least 2 of 3 leaders have
candle context (trend_aligned_pct not None).
"""
from __future__ import annotations

import re

import pytest

LEADERS = [
    "0xe2823659be02e0f48a4660e4da008b5e1abfdf29",
    "0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa",
    "0xbe10fd36393c8b677281d0bc2cf1bb8c98ad4b34",
]


@pytest.mark.live
def test_live_fingerprints(tmp_path):
    from discovery import db
    from discovery.thesis import config as C
    from discovery.thesis import public
    from discovery.thesis.template import render_markdown, render_summary
    from hl import HlVenue

    conn = db.connect(tmp_path / "thesis_live.db")
    venue = public._default_venue()
    assert isinstance(venue, HlVenue)
    known = {t for t, *_ in C.TAG_RULES}
    with_context = 0
    for addr in LEADERS:
        fp = public.fingerprint(addr, 30, venue, conn=conn, refresh=True)
        print(f"\n=== {addr}  trips={fp.trips_analyzed} style={fp.style.value if fp.style else '-'}")
        print(fp.summary)
        print("tags:", ", ".join(fp.tags) or "-")
        for c in fp.caveats:
            print("caveat:", c)
        for e in fp.examples:
            print(f"  ex: {e.why_shown}: {e.coin} {e.side} {e.hold_h:.1f}h {e.net_pnl_usd:+.0f} "
                  f"trend={e.context.trend_aligned} pb={e.context.pullback} bo={e.context.breakout}")
        n = len(re.findall(r"\.(?:\s|$)", fp.summary))
        assert fp.trips_analyzed > 0, f"{addr}: no trips"
        assert 4 <= n <= 8, f"{addr}: {n} sentences"
        text = fp.summary + render_markdown(fp)
        assert "—" not in text and "–" not in text
        assert set(fp.tags) <= known
        assert 1 <= len(fp.examples) <= 8
        assert len({(e.opened_ms, e.coin) for e in fp.examples}) == len(fp.examples)
        assert render_summary(fp) == fp.summary
        with_context += fp.trend_aligned_pct is not None
    assert with_context >= 2
