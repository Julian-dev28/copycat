"""What the /api/accounts routes talk to: vault.public (secrets), hl (reads),
engine.public (copy margin), discovery.scout.public (metrics). Every import is
lazy so the api starts even if one service is missing. Tests replace the hl,
engine and discovery reads by overriding `get_accounts_backend`; the vault runs
for real against a temp data dir.

HL reads here run at background priority (never the engine's rate reserve).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from contracts.models import EngineStatus

logger = logging.getLogger(__name__)

FILLS_WINDOW_MS = 30 * 24 * 3600 * 1000
LEDGER_WINDOW_MS = 365 * 24 * 3600 * 1000


class AccountsBackend:
    def vault(self) -> Any:
        from vault import public  # type: ignore[import-not-found]
        return public

    # ── hl reads ────────────────────────────────────────────────────────────
    def _venue(self) -> Any:
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        from hl import HlVenue  # type: ignore[import-not-found]
        return HlVenue()

    def account_state(self, address: str) -> Optional[Dict[str, Any]]:
        return self._venue().account_state(address)

    def extras(self, address: str) -> Optional[Dict[str, Any]]:
        return self._venue().extras(address)

    def portfolio(self, address: str) -> Optional[List[Any]]:
        return self._venue().portfolio(address)

    def fills(self, address: str) -> Optional[List[Dict[str, Any]]]:
        now = int(time.time() * 1000)
        return self._venue().fills(address, now - FILLS_WINDOW_MS, now)

    def historical_orders(self, address: str) -> Optional[List[Dict[str, Any]]]:
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        from hl import history  # type: ignore[import-not-found]
        return history.historical_orders(address)

    def ledger_updates(self, address: str) -> Optional[List[Dict[str, Any]]]:
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        from hl import history  # type: ignore[import-not-found]
        return history.ledger_updates(address, int(time.time() * 1000) - LEDGER_WINDOW_MS)

    def spot_balances(self, address: str) -> Optional[List[Dict[str, Any]]]:
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        from hl import history  # type: ignore[import-not-found]
        return history.spot_balances(address)

    def funding_facts(self) -> Dict[str, Any]:
        """Bridge, USDC, minimum deposit, withdraw fee for this network (static, no read)."""
        from hl import accounts  # type: ignore[import-not-found]
        return accounts.funding_info()

    # ── other services ──────────────────────────────────────────────────────
    def engine_status(self, address: str) -> Optional[EngineStatus]:
        """That account's own last engine snapshot (engine-<address>.db)."""
        try:
            from engine import public  # type: ignore[import-not-found]
            return public.status(address)
        except Exception as exc:
            logger.warning("engine status for %s unavailable: %s", address, type(exc).__name__)
            return None

    def metrics(self, address: str) -> Optional[Dict[str, Any]]:
        """discovery.scout.public.account_metrics(address) -> dict of AccountSummary
        metric fields, when discovery exposes it. None until then."""
        try:
            from discovery.scout import public  # type: ignore[import-not-found]
        except Exception:
            return None
        fn = getattr(public, "account_metrics", None)
        if fn is None:
            return None
        try:
            return fn(address)
        except Exception as exc:
            logger.warning("account_metrics(%s) failed: %s", address, type(exc).__name__)
            return None
