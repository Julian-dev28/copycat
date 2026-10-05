"""Append-only audit log of money movements: $COPYCAT_DATA_DIR/vault/audit.jsonl.

One JSON line per attempt that reached a guard (EngineEvent-like: ts_ms, action,
reason), whatever the outcome:

  {"ts_ms", "action": "usd_class_transfer"|"usd_send"|"withdraw", "path": "browser"|"passphrase",
   "outcome": "ok"|"refused"|"rejected"|"error", "account_id", "address", "amount_usd",
   "to_perp", "destination", "nonce", "reason"}

Never a passphrase, key, signature or typed data: `record` only accepts the
fields above (an unknown field is a programming error and raises). Reasons are
VaultError messages, which are secret-free by contract (vault/errors.py).
File mode 0600, appended under the vault lock so lines never interleave.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import fsio
from .approval import now_ms

logger = logging.getLogger(__name__)

AUDIT_FILE = "audit.jsonl"
_FIELDS = ("kind", "path", "outcome", "account_id", "address", "amount", "to_perp", "destination", "nonce",
           "reason")


def audit_path() -> Path:
    return fsio.vault_dir() / AUDIT_FILE


def record(**fields: Any) -> Dict[str, Any]:
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"audit.record: unknown fields {sorted(unknown)}")
    amount = fields.get("amount")
    line: Dict[str, Any] = {
        "ts_ms": now_ms(), "action": fields.get("kind"), "path": fields.get("path"),
        "outcome": fields.get("outcome"), "account_id": fields.get("account_id"), "address": fields.get("address"),
        "amount_usd": float(amount) if amount not in (None, "") else None, "to_perp": fields.get("to_perp"),
        "destination": fields.get("destination"), "nonce": fields.get("nonce"),
        "reason": (str(fields["reason"])[:300] if fields.get("reason") else None),
    }
    data = (json.dumps(line, separators=(",", ":")) + "\n").encode()
    try:
        with fsio.locked():
            path = audit_path()
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, fsio.FILE_MODE)
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as exc:   # never lose the action's own result over the log; say so loudly
        logger.error("[vault.audit] could not append to %s: %s", AUDIT_FILE, type(exc).__name__)
    logger.info("[vault.audit] %s %s %s %s USDC %s", line["action"], line["path"], line["outcome"],
                line["amount_usd"], line["address"])
    return line


def read(limit: int = 200) -> List[Dict[str, Any]]:
    """Newest last. Unparseable lines are skipped."""
    path = audit_path()
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for raw in fsio.read_private(path).decode(errors="replace").splitlines()[-limit:]:
        try:
            row: Optional[Dict[str, Any]] = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out
