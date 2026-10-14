"""Fakes for engine.public / discovery.scout.public / discovery.thesis.public,
satisfying the EngineClient / ScoutClient / ThesisClient Protocols. Tests inject these via
app.dependency_overrides so no test ever imports the real `engine` or
`discovery` packages (which may not exist yet / are built in parallel).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from api.engine_client import EngineUnavailable
from api.market_client import MarketUnavailable
from api.schemas import CandleView
from api.scout_client import ScoutBusy, ScoutUnavailable
from api.thesis_client import ThesisUnavailable

from contracts.models import (
    AccountRisk,
    CustomWallet,
    EngineEvent,
    EngineStatus,
    EntryContext,
    LeaderFillView,
    LeaderOverride,
    OpenOrderView,
    PnlTier,
    PnlWindow,
    RiskStats,
    ScoutPresets,
    ScoutSimTerms,
    ScoutStatus,
    Settings,
    SizeTier,
    StrategyFingerprint,
    Thesis,
    TradeExample,
    TraderPage,
    TraderProfile,
    TraderRow,
    TraderScore,
    TradeStats,
    WhatIfResult,
    WindowPerf,
)

OUR_ADDRESS = "0x" + "1" * 40      # the fixture app's COPYCAT_ACCOUNT_ADDRESS


class FakeEngineClient:
    def __init__(self) -> None:
        self._status = EngineStatus(running=True, enabled=False, dry_run=True)
        self.event_log: List[EngineEvent] = []
        self.preview_calls: List[tuple] = []
        self.preview_result: Any = None        # a WalletPreview, or an exception to raise
        self.ledgers: Dict[str, Dict[str, Any]] = {}   # v8 wallet_ledgers()
        self.archive_refused: Optional[str] = None
        self.book_result: Any = None           # v9 leader_book(): a list, or an exception

    def leader_book(self, address: str) -> List[Dict[str, Any]]:
        """v9: `book_result` if set, else his positions as the preview shows them."""
        if isinstance(self.book_result, Exception):
            raise self.book_result
        if self.book_result is not None:
            return self.book_result
        pv = self.preview_result
        return [{"coin": s.coin, "side": s.side, "notional_usd": s.his_notional_usd}
                for s in (pv.slices if pv is not None and not isinstance(pv, Exception) else [])]

    def preview(self, address: str, req: Any, settings: Settings) -> Any:
        self.preview_calls.append((address, req, settings))
        if isinstance(self.preview_result, Exception):
            raise self.preview_result
        return self.preview_result

    def status(self) -> EngineStatus:
        return self._status

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]:
        evs = self.event_log
        if since_ms is not None:
            evs = [e for e in evs if e.ts_ms >= since_ms]
        return list(reversed(evs))[:limit]

    # v8
    def leader_events(self, address: str, limit: int,
                      before_ms: Optional[int] = None) -> List[EngineEvent]:
        evs = [e for e in reversed(self.event_log) if e.leader == address
               and (before_ms is None or e.ts_ms < before_ms)]
        return evs[:limit]

    def wallet_ledgers(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.ledgers)

    def archive(self, address: str, now_ms: int) -> Dict[str, Any]:
        from api.engine_client import ArchiveRefused
        if self.archive_refused:
            raise ArchiveRefused(self.archive_refused)
        row = self.ledgers.setdefault(address, {"leader": address, "invested_ms": None,
                                                "realized_pnl_usd": 0.0, "fees_usd": 0.0,
                                                "terms": {}, "updated_ms": now_ms})
        row["archived_ms"] = now_ms
        return row


class UnavailableEngineClient:
    """Simulates services/engine not being importable yet."""

    def status(self) -> EngineStatus:
        raise EngineUnavailable("services/engine isn't importable yet: boom")

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]:
        raise EngineUnavailable("services/engine isn't importable yet: boom")

    def preview(self, address: str, req: Any, settings: Settings) -> Any:
        raise EngineUnavailable("services/engine isn't importable yet: boom")


# ── Scout ────────────────────────────────────────────────────────────────────

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40
ADDR_BUILDING = "0x" + "c" * 40


def make_score(address: str) -> TraderScore:
    return TraderScore(
        address=address, account_value_usd=50_000, pnl_30d_usd=1_000, roi_30d_pct=2.0,
        pnl_all_time_usd=5_000, volume_30d_usd=1e6, fills_30d=100, opens_per_day=2.0,
        sim_return_pct=3.0, sim_max_drawdown_pct=-4.0, sim_liquidations=0, sim_copies=20,
        sim_skipped_min_order=0, sim_fees_usd=1.0, score=0.5,
    )


def make_row(address: str) -> TraderRow:
    return TraderRow(
        address=address, account_value_usd=50_000, size_tier=SizeTier.M, pnl_tier=PnlTier.up,
        perf=[WindowPerf(window=w, pnl_usd=1.0, roi_pct=1.0, volume_usd=1.0) for w in PnlWindow],
        risk_30d=RiskStats(window=PnlWindow.month),
        trades_30d=TradeStats(window=PnlWindow.month, trips=10, wins=6, long_trips=5, short_trips=5),
        score=make_score(address),
        in_book=True,   # deliberately wrong: the api must overwrite it from Settings.leaders
    )


def make_profile(address: str) -> TraderProfile:
    return TraderProfile(
        row=make_row(address),
        account=AccountRisk(perps_usd=1, spot_usd=0, staked_usd=0, account_leverage=1,
                            margin_usage_pct=1, long_notional_usd=1, short_notional_usd=0,
                            unrealized_pnl_usd=0),
        positions=[], positions_as_of_ms=0, pnl_curve={}, value_curve={}, sim_curve=[],
        daily_pnl=[], risk=[], trades=[], longest_win_streak_days=0, coins=[],
    )


class FakeScoutClient:
    """In-memory discovery.scout.public. Two traders on the board (A, B);
    ADDR_BUILDING returns a ScoutStatus (the 202 path); anything else None."""

    def __init__(self) -> None:
        self.queries: List[Dict[str, Any]] = []
        self.what_if_calls: List[tuple] = []
        self.fills_calls: List[tuple] = []
        self.refresh_busy = False
        self.what_if_busy = False
        self.what_if_hook: Any = None          # called inside what_if (concurrency tests)
        self.what_if_missing: set = set()      # addresses with no cached Scout stats (LookupError)
        self.refresh_id = "r1"
        self._status = ScoutStatus(refresh_id="r1", state="idle", last_ok_ms=1)
        self._terms = ScoutSimTerms()

    def page(self, query: Dict[str, Any]) -> TraderPage:
        self.queries.append(query)
        rows = [make_row(ADDR_A), make_row(ADDR_B)]
        return TraderPage(as_of_ms=1, refresh_id=self.refresh_id, settings_hash="h1",
                          cohort_size=2, total=2, rows=rows)

    def profile(self, address: str) -> Union[TraderProfile, ScoutStatus, None]:
        if address == ADDR_BUILDING:
            return ScoutStatus(refresh_id=None, state="running", stage="stats", done=1, total=2)
        if address in (ADDR_A, ADDR_B):
            return make_profile(address)
        return None

    def fills(self, address: str, before_ms: Optional[int], limit: int) -> List[LeaderFillView]:
        self.fills_calls.append((address, before_ms, limit))
        return [LeaderFillView(time_ms=1, coin="BTC", side="B", dir="Open Long", px=1.0, sz=1.0,
                               notional_usd=1.0, closed_pnl_usd=0.0, fee_usd=0.0)]

    def orders(self, address: str) -> List[OpenOrderView]:
        return [OpenOrderView(oid=7, coin="BTC", side="B", limit_px=100.0, sz=1.0, orig_sz=1.0,
                              notional_usd=100.0, time_ms=1)]

    def what_if(self, address: str, settings: Settings, sim_equity_usd: float,
                override: LeaderOverride) -> WhatIfResult:
        if self.what_if_busy:
            raise ScoutBusy("discovery says a what-if is running")
        if self.what_if_hook is not None:
            self.what_if_hook()
        if address in self.what_if_missing:
            raise LookupError(f"no Scout stats for {address} yet")
        self.what_if_calls.append((address, settings, sim_equity_usd, override))
        return WhatIfResult(score=make_score(address), sim_curve=[])

    def presets(self) -> ScoutPresets:
        return ScoutPresets(refresh_id="r1", coins=["BTC"], coin_counts={"BTC": 2}, hip3_count=1, total=2)

    def status(self) -> ScoutStatus:
        return self._status

    def refresh(self) -> ScoutStatus:
        if self.refresh_busy:
            raise ScoutBusy("a Scout refresh is already running")
        self._status = ScoutStatus(refresh_id="r1", state="running", stage="leaderboard")
        return self._status

    # v16 sim terms: in-memory, defaults to the ScoutSimTerms() reference
    def sim_terms_get(self) -> ScoutSimTerms:
        return self._terms

    def sim_terms_set(self, terms: ScoutSimTerms) -> ScoutSimTerms:
        self._terms = terms
        return self._terms

    # v15 custom wallets: an in-memory set; A and B count as "on the board"
    def custom_list(self) -> List[CustomWallet]:
        return [CustomWallet(address=a, added_ms=1, on_board=a in (ADDR_A, ADDR_B), queued=a not in (ADDR_A, ADDR_B))
                for a in sorted(getattr(self, "custom", set()))]

    def custom_add(self, address: str) -> Optional[CustomWallet]:
        if not address.startswith("0x") or len(address) != 42:
            return None
        self.custom = getattr(self, "custom", set()) | {address}
        return next(c for c in self.custom_list() if c.address == address)

    def custom_remove(self, address: str) -> bool:
        had = address in getattr(self, "custom", set())
        self.custom = getattr(self, "custom", set()) - {address}
        return had


class UnavailableScoutClient:
    """Simulates discovery.scout not being importable yet: every call raises."""

    def __getattr__(self, name: str) -> Any:
        def _raise(*a: Any, **k: Any) -> Any:
            raise ScoutUnavailable("discovery.scout isn't importable yet: boom")
        return _raise


# ── Strategy thesis / market ─────────────────────────────────────────────────

def make_example(i: int) -> TradeExample:
    return TradeExample(coin="BTC", side="long", opened_ms=i, closed_ms=i + 1, hold_h=1.0, adds=0,
                        net_pnl_usd=float(i), return_pct=1.0, context=EntryContext(hour_utc=i % 24),
                        why_shown=f"example {i}")


def make_fingerprint(address: str, window_days: int = 30, as_of_ms: int = 1000) -> StrategyFingerprint:
    return StrategyFingerprint(address=address, as_of_ms=as_of_ms, window_days=window_days,
                               trips_analyzed=40, summary="buys breakouts",
                               examples=[make_example(i) for i in range(8)])


class FakeThesisClient:
    """In-memory discovery.thesis.public. `fingerprint` is what the job
    queue calls (in the real client, a child process)."""

    def __init__(self) -> None:
        self.fingerprint_calls: List[tuple] = []
        self.fail_with: Optional[BaseException] = None
        self.saved: List[Thesis] = []
        self.stored: List[Thesis] = []

    def fingerprint(self, address: str, window_days: int) -> StrategyFingerprint:
        self.fingerprint_calls.append((address, window_days))
        if self.fail_with is not None:
            raise self.fail_with
        return make_fingerprint(address, window_days, as_of_ms=1000 + len(self.fingerprint_calls))

    def theses(self, address: str) -> List[Thesis]:
        return [t for t in self.stored + self.saved if t.address == address]

    def save(self, thesis: Thesis) -> None:
        self.saved.append(thesis)


class UnavailableThesisClient:
    def __getattr__(self, name: str) -> Any:
        def _raise(*a: Any, **k: Any) -> Any:
            raise ThesisUnavailable("discovery.thesis isn't importable yet: boom")
        return _raise


class FakeMarketClient:
    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[CandleView]:
        self.calls.append((coin, interval, start_ms, end_ms))
        return [CandleView(t_ms=start_ms, o=1, h=2, l=0.5, c=1.5, v=10)]


class UnavailableMarketClient:
    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> List[CandleView]:
        raise MarketUnavailable("discovery.public has no candles() yet")

