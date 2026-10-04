"""The api is the only writer of data/settings.json. Every write is atomic
(tmp file in the same dir + os.replace) and every read-modify-write is
serialized by an flock on a sidecar lock file, so two concurrent PATCHes
never lose one's update to a race.

flock is per *open file description*, not per process: two threads (or
processes) each opening their own fd on the same lock file genuinely block
each other at the kernel level, which is what makes the concurrency test in
tests/test_settings_concurrency.py a real test and not a coincidence.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

from contracts.models import (
    MAX_LEADERS,
    ExposureMode,
    LeaderOverride,
    Settings,
    SizingMode,
    WalletCopyRequest,
    norm_addr,
)

from .schemas import SettingsPatch

# Mirrors contracts.models._ADDR. Kept local (not imported) because it's a
# private name there and POST /api/leaders needs a plain ValueError/400 path
# that's distinct from the 422-via-Settings-validation path PATCH uses.
_ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")


class LeaderLimitError(Exception):
    """Raised by add_leader() at MAX_LEADERS. Routes map this to HTTP 409."""


class OwnAddressError(ValueError):
    """Our own account (COPYCAT_ACCOUNT_ADDRESS) was given as a leader.
    Copying ourselves would mirror every copy back onto itself. HTTP 400."""


class SettingsStore:
    def __init__(self, data_dir: Path, our_address: Optional[str] = None):
        self.our_address = norm_addr(our_address) if our_address else None
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "settings.json"
        self.lock_path = self.data_dir / "settings.json.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def load(self) -> Settings:
        """A missing file serves defaults. Never writes."""
        if not self.path.exists():
            return Settings()
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Settings(**data)

    def _check_not_us(self, settings: Settings) -> None:
        if self.our_address and self.our_address in settings.leaders:
            raise OwnAddressError(
                f"{self.our_address} is this copycat's own account (COPYCAT_ACCOUNT_ADDRESS); "
                f"it cannot be a leader")

    def _write_atomic(self, settings: Settings) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = settings.model_dump(mode="json")
        fd, tmp_path = tempfile.mkstemp(
            prefix=".settings-", suffix=".tmp", dir=self.data_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def put(self, settings: Settings) -> Settings:
        """Full replace. `settings` is already a validated Settings
        instance (FastAPI validates the PUT body against Settings before
        this is ever called), so there's nothing left to validate here.
        """
        self._check_not_us(settings)
        with self._locked():
            self._write_atomic(settings)
        return settings

    def patch(self, patch: SettingsPatch) -> Settings:
        """Shallow-merge `patch` onto the current settings and persist.

        - Top-level fields the client set (per `model_fields_set`) replace
          the current value outright (a provided `leaders` list replaces
          the whole list, it isn't merged element-wise).
        - `leader_overrides`, if provided, is merged per-leader: a provided
          override REPLACES that leader's entire override (not merged
          field by field with its old override); a `null` value clears it.
        - The merge is validated via `Settings(**merged)` BEFORE writing.
          On failure this raises pydantic.ValidationError and nothing is
          written -- the caller (the PATCH route) turns that into a 422.
        """
        with self._locked():
            current = self.load()
            data = current.model_dump(mode="json")

            provided = patch.model_fields_set
            for key in provided:
                if key == "leader_overrides":
                    continue
                data[key] = getattr(patch, key)

            if "leader_overrides" in provided:
                overrides = dict(current.leader_overrides)
                incoming = patch.leader_overrides or {}
                for addr, override in incoming.items():
                    addr_n = norm_addr(addr)
                    if override is None:
                        overrides.pop(addr_n, None)
                    else:
                        overrides[addr_n] = override
                data["leader_overrides"] = overrides

            merged = Settings(**data)  # raises ValidationError -> nothing written
            if "leaders" in provided:   # never block an unrelated PATCH on a legacy file
                self._check_not_us(merged)
            self._write_atomic(merged)
            return merged

    def add_leader(self, address: str) -> Settings:
        """Idempotent if already a leader. Raises ValueError (-> 400) on a
        malformed address, LeaderLimitError (-> 409) at MAX_LEADERS.
        """
        addr = norm_addr(address)
        if not _ADDR_RE.match(addr):
            raise ValueError(f"not a 0x address: {address!r}")
        if self.our_address and addr == self.our_address:
            raise OwnAddressError(
                f"{addr} is this copycat's own account (COPYCAT_ACCOUNT_ADDRESS); it cannot be a leader")
        with self._locked():
            current = self.load()
            if addr in current.leaders:
                return current
            if len(current.leaders) >= MAX_LEADERS:
                raise LeaderLimitError(f"max {MAX_LEADERS} leaders")
            updated = current.model_copy(
                update={"leaders": current.leaders + [addr]}
            )
            validated = Settings(**updated.model_dump(mode="json"))
            self._write_atomic(validated)
            return validated

    def remove_leader(self, address: str) -> Settings:
        """Idempotent: removing a leader that isn't present is a no-op.
        Also drops that leader's override, if any.
        """
        addr = norm_addr(address)
        with self._locked():
            current = self.load()
            if addr not in current.leaders and addr not in current.leader_overrides:
                return current
            updated = current.model_copy(
                update={
                    "leaders": [a for a in current.leaders if a != addr],
                    "leader_overrides": {
                        a: o for a, o in current.leader_overrides.items() if a != addr
                    },
                }
            )
            validated = Settings(**updated.model_dump(mode="json"))
            self._write_atomic(validated)
            return validated

    # ── Trade page wallets ──────────────────────────────────────────────

    def _valid_leader_addr(self, address: str) -> str:
        addr = norm_addr(address)
        if not _ADDR_RE.match(addr):
            raise ValueError(f"not a 0x address: {address!r}")
        if self.our_address and addr == self.our_address:
            raise OwnAddressError(
                f"{addr} is this copycat's own account (COPYCAT_ACCOUNT_ADDRESS); it cannot be a leader")
        return addr

    def copy_wallet(self, address: str, req: WalletCopyRequest, now_ms: int) -> Settings:
        """Invest in (or adjust) a wallet in ONE locked write: add the leader
        if new (LeaderLimitError at MAX_LEADERS), then:

        - settings_source global: the wallet runs entirely on the Settings
          tab. Its override is cleared down to bookkeeping only:
          `LeaderOverride(invested_ms=...)`, which no sizing reads, so
          `for_leader` equals the book-wide settings. `invested_ms` keeps
          the engine's per-wallet PnL ledger honest (a re-add resets it).
        - settings_source custom: the override becomes allocation sizing with
          the ticket's terms (allocation, exposure, target leverage, and when
          given margin mode, worse-entry %, small-account mode, leverage
          mode, leverage, only_new_positions). Other fields of a previous
          override are kept.

        `invested_ms` is `now_ms` for a new wallet or one without it yet; a
        re-post (adjust, or a global <-> custom switch) keeps it, so the
        ledger is not reset. Raises ValueError (400) on a bad address,
        OwnAddressError (400) for our own account."""
        addr = self._valid_leader_addr(address)
        if (req.settings_source == "custom" and req.exposure_mode == ExposureMode.target
                and req.target_leverage is None):
            raise ValueError("target_leverage is required for exposure_mode target")
        with self._locked():
            current = self.load()
            newly_added = addr not in current.leaders
            if newly_added and len(current.leaders) >= MAX_LEADERS:
                raise LeaderLimitError(f"max {MAX_LEADERS} leaders")
            prev = current.leader_overrides.get(addr)
            fresh = newly_added or prev is None or prev.invested_ms is None
            invested_ms = now_ms if fresh else prev.invested_ms
            if req.settings_source == "global":
                override = LeaderOverride(invested_ms=invested_ms)
            else:
                data = prev.model_dump() if prev is not None else {}
                data.update({
                    "sizing_mode": SizingMode.allocation, "allocation_usd": req.allocation_usd,
                    "exposure_mode": req.exposure_mode, "invested_ms": invested_ms,
                })
                for k in ("target_leverage", "margin_mode", "max_worse_entry_pct",
                          "small_account_mode", "leverage_mode", "leverage", "only_new_positions"):
                    v = getattr(req, k)
                    if v is not None:
                        data[k] = v
                override = LeaderOverride.model_validate(data)
            overrides = dict(current.leader_overrides)
            overrides[addr] = override
            leaders = current.leaders + [addr] if newly_added else list(current.leaders)
            merged = Settings(**{**current.model_dump(mode="json"), "leaders": leaders,
                                 "leader_overrides": {a: o.model_dump(mode="json")
                                                      for a, o in overrides.items()}})
            self._write_atomic(merged)
            return merged

    def stop_wallet(self, address: str) -> Tuple[Settings, bool]:
        """Remove a wallet and its override (one locked write). Returns
        `(settings, was_in_book)`. Never raises for an unknown address."""
        addr = norm_addr(address)
        with self._locked():
            current = self.load()
            was_in_book = addr in current.leaders
            if not was_in_book and addr not in current.leader_overrides:
                return current, False
            merged = Settings(**{
                **current.model_dump(mode="json"),
                "leaders": [a for a in current.leaders if a != addr],
                "leader_overrides": {a: o.model_dump(mode="json")
                                     for a, o in current.leader_overrides.items() if a != addr},
            })
            self._write_atomic(merged)
            return merged, was_in_book


def settings_source(override: Optional[LeaderOverride]) -> str:
    """"global" when a wallet has no per-wallet terms (no override, or only
    the `invested_ms` bookkeeping a global copy writes), else "custom"."""
    if override is None:
        return "global"
    terms = {k: v for k, v in override.model_dump().items() if v is not None and k != "invested_ms"}
    return "custom" if terms else "global"
