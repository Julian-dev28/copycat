"""Gate tests for the engine's ledger read: hl.history.ledger_since (pages,
dedupe, never a partial list), its weight, and HlVenue.ledger_updates."""
from __future__ import annotations

from hl import history
from hl import venue as venue_mod
from hl.rate_limit import endpoint_weight, item_surcharge


def _row(t, kind="deposit", usdc="1.0", h=None):
    return {"time": t, "hash": h or f"0x{t:x}", "delta": {"type": kind, "usdc": usdc}}


def _pager(pages, calls):
    def fake(user, start_ms, end_ms=None):
        calls.append(start_ms)
        return pages.pop(0) if pages else []
    return fake


def test_one_short_page_is_the_whole_answer(monkeypatch):
    calls = []
    monkeypatch.setattr(history, "ledger_updates", _pager([[_row(5), _row(3)]], calls))
    rows = history.ledger_since("0xabc", 1)
    assert [r["time"] for r in rows] == [3, 5]          # oldest first
    assert calls == [1]


def test_a_full_page_pages_forward_from_its_last_time_and_dedupes(monkeypatch):
    calls = []
    p1 = [_row(1), _row(2), _row(3)]
    p2 = [_row(3), _row(3, "withdraw", h="0xother"), _row(4)]     # 3 repeats, a new row shares t=3
    monkeypatch.setattr(history, "ledger_updates", _pager([p1, p2[:2], ], calls))
    rows = history.ledger_since("0xabc", 0, page_rows=3)
    assert calls == [0, 3]
    assert [(r["time"], r["delta"]["type"]) for r in rows] == [
        (1, "deposit"), (2, "deposit"), (3, "deposit"), (3, "withdraw")]


def test_a_failed_page_is_none_never_a_partial_list(monkeypatch):
    calls = []
    monkeypatch.setattr(history, "ledger_updates", _pager([[_row(1), _row(2)], None], calls))
    assert history.ledger_since("0xabc", 0, page_rows=2) is None


def test_more_rows_than_the_page_budget_is_none(monkeypatch):
    pages = [[_row(2 * i), _row(2 * i + 1)] for i in range(10)]
    monkeypatch.setattr(history, "ledger_updates", _pager(pages, []))
    assert history.ledger_since("0xabc", 0, max_pages=3, page_rows=2) is None


def test_a_full_page_of_repeats_is_none(monkeypatch):
    same = [_row(7, h="0xa"), _row(7, h="0xb")]
    monkeypatch.setattr(history, "ledger_updates", _pager([same, list(same)], []))
    assert history.ledger_since("0xabc", 0, page_rows=2) is None


def test_malformed_rows_are_none(monkeypatch):
    monkeypatch.setattr(history, "ledger_updates", lambda u, s, e=None: [{"time": 1, "delta": "x"}])
    assert history.ledger_since("0xabc", 0) is None
    monkeypatch.setattr(history, "ledger_updates", lambda u, s, e=None: [{"time": None, "delta": {}}])
    assert history.ledger_since("0xabc", 0) is None


def test_ledger_weight_is_20_plus_1_per_20_rows():
    assert endpoint_weight("userNonFundingLedgerUpdates") == 20
    assert item_surcharge("userNonFundingLedgerUpdates", 2000) == 100
    assert item_surcharge("userNonFundingLedgerUpdates", 3) == 1


def test_ledger_updates_sends_the_documented_payload(monkeypatch):
    sent = []

    def fake_post(path, payload, **kw):
        sent.append((path, payload))
        return [_row(9)]
    monkeypatch.setattr(history, "http_post", fake_post)
    rows = venue_mod.HlVenue().ledger_updates("0xabc", 1234)
    assert rows == [_row(9)]
    assert sent == [("/info", {"type": "userNonFundingLedgerUpdates", "user": "0xabc", "startTime": 1234})]


def test_venue_ledger_updates_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(history, "ledger_since", boom)
    assert venue_mod.HlVenue().ledger_updates("0xabc", 0) is None
