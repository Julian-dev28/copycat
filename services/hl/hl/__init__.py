"""hl: every Hyperliquid call for copycat lives here -- timeouts, meta
caching, rate limiting, and signing with the agent key.

Public surface: `hl.HlVenue`, implementing `contracts.venue.Venue`. Every
other service (engine, discovery) talks to Hyperliquid only through that
class; nothing else in this package is a contract. See services/hl/README.md
for the full write-up (keys, rate limits, network selection).
"""
from __future__ import annotations

from .venue import HlVenue

__all__ = ["HlVenue"]
