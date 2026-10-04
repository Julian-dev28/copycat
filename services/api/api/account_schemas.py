"""api-local shapes for /api/accounts (the shared ones live in contracts.models v6)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)


class TransferResult(BaseModel):
    ok: bool
    from_address: str
    to_address: str
    amount_usd: float


class AccountHistory(BaseModel):
    kind: Literal["fills", "orders", "transfers", "balances"]
    rows: List[Dict[str, Any]]


class ImportEnvStatus(BaseModel):
    """GET /api/accounts/import-env: whether the one-click migration applies."""
    available: bool
    address: Optional[str] = None
    reason: Optional[str] = None
