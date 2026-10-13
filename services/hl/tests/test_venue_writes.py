"""Gate tests for HlVenue's write path under contract v2 (contracts/venue.py):
cloid passthrough, order_status, full-vs-partial fills, ambiguous results,
the slippage cap, reduce-only never bumped to the $10 floor, close()
confirmed by a fresh read, and the main-wallet-key guard. Fake SDK + fake
http_post, no network, <2s.
"""
from __future__ import annotations

import pytest
import requests
from eth_account import Account
from hl import meta, sdk, sizing
from hl import venue as venue_mod
from hl.venue import HlVenue
from hyperliquid.utils.error import ClientError, ServerError
from hyperliquid.utils.types import Cloid

CLOID = "0x" + "ab" * 16
ACCOUNT = "0x" + "22" * 20


class _FakeExchange:
    """Records every order; returns `result` or raises `exc`."""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def order(self, coin, is_buy, sz, px, order_type, reduce_only=False, cloid=None):
        self.calls.append({"coin": coin, "is_buy": is_buy, "sz": sz, "px": px,
                           "order_type": order_type, "reduce_only": reduce_only, "cloid": cloid})
        if self.exc:
            raise self.exc
        return self.result


def _filled(total_sz="1.0", avg_px="100.5"):
    return {"status": "ok", "response": {"type": "order", "data": {"statuses": [
        {"filled": {"totalSz": total_sz, "avgPx": avg_px, "oid": 77}},
    ]}}}


def _book(bid, ask):
    return {"coin": "BTC", "levels": [[{"px": str(bid), "sz": "5", "n": 1}],
                                      [{"px": str(ask), "sz": "5", "n": 1}]]}


@pytest.fixture
def venue(write_creds, monkeypatch):
    """Write creds + sz_decimals=2 + a sane book (bid 99.9 / ask 100.1 around
    mid 100). Returns (HlVenue, fake exchange, post-call recorder)."""
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 2)
    posts = []
    book = {"v": _book(99.9, 100.1)}

    def fake_post(path, payload, **kw):
        posts.append(payload)
        if payload["type"] == "l2Book":
            return book["v"]
        return None

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    fake = _FakeExchange(result=_filled())
    monkeypatch.setattr(sdk, "get_exchange", lambda: fake)
    return HlVenue(), fake, posts, book


# ── 1. cloid ──────────────────────────────────────────────────────────────────

def test_market_passes_cloid_as_sdk_cloid(venue):
    v, fake, _, _ = venue
    out = v.market("BTC", True, 1.0, 100.0, cloid=CLOID)
    assert out["ok"] is True
    sent = fake.calls[0]["cloid"]
    assert isinstance(sent, Cloid) and sent.to_raw() == CLOID


def test_market_without_cloid_sends_none(venue):
    v, fake, _, _ = venue
    v.market("BTC", True, 1.0, 100.0)
    assert fake.calls[0]["cloid"] is None


def test_market_invalid_cloid_refused_before_send(venue):
    v, fake, _, _ = venue
    out = v.market("BTC", True, 1.0, 100.0, cloid="0x1234")
    assert out["ok"] is False and "invalid cloid" in out["error"]
    assert fake.calls == []


def _status_venue(monkeypatch, response):
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", ACCOUNT)
    seen = []

    def fake_post(path, payload, **kw):
        seen.append((path, payload))
        return response

    monkeypatch.setattr(venue_mod, "http_post", fake_post)
    return HlVenue(), seen


def test_order_status_sends_account_and_cloid_string(monkeypatch):
    """Same body the SDK's Info.query_order_by_cloid builds: the cloid hex
    string goes in the "oid" field, user is OUR account."""
    v, seen = _status_venue(monkeypatch, {"status": "order", "order": {"order": {}, "status": "filled"}})
    assert v.order_status(CLOID) == "filled"
    assert seen == [("/info", {"type": "orderStatus", "user": ACCOUNT, "oid": CLOID})]


@pytest.mark.parametrize("raw,expected", [
    ("open", "open"),
    ("filled", "filled"),
    ("canceled", "canceled"),
    ("marginCanceled", "canceled"),
    ("reduceOnlyCanceled", "canceled"),
    ("scheduledCancel", "canceled"),
    ("rejected", "rejected"),
    ("minTradeNtlRejected", "rejected"),
    ("iocCancelRejected", "rejected"),
    ("triggered", "triggered"),
])
def test_order_status_maps_hl_statuses(monkeypatch, raw, expected):
    v, _ = _status_venue(monkeypatch, {"status": "order", "order": {"order": {}, "status": raw}})
    assert v.order_status(CLOID) == expected


def test_order_status_unknown_oid(monkeypatch):
    v, _ = _status_venue(monkeypatch, {"status": "unknownOid"})
    assert v.order_status(CLOID) == "unknown"


def test_order_status_none_on_read_failure(monkeypatch):
    v, _ = _status_venue(monkeypatch, None)
    assert v.order_status(CLOID) is None


def test_order_status_none_on_unexpected_shape(monkeypatch):
    v, _ = _status_venue(monkeypatch, {"status": "order", "order": {}})
    assert v.order_status(CLOID) is None


def test_order_status_none_without_account_or_with_bad_cloid(monkeypatch):
    v, seen = _status_venue(monkeypatch, {"status": "unknownOid"})
    assert v.order_status("not-a-cloid") is None
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS")
    assert v.order_status(CLOID) is None
    assert seen == []  # neither case touched the network


# ── 2. ambiguous results ─────────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [
    requests.exceptions.ReadTimeout("read timed out"),
    requests.exceptions.ConnectionError("connection reset"),
    TimeoutError("timed out"),
    ServerError(502, "bad gateway"),
])
def test_exchange_timeout_or_dropped_connection_is_ambiguous(venue, exc):
    v, fake, _, _ = venue
    fake.exc = exc
    out = v.market("BTC", True, 1.0, 100.0, cloid=CLOID)
    assert out["ok"] is False
    assert out["ambiguous"] is True
    assert out["error"]


@pytest.mark.parametrize("exc", [
    ValueError("signing failed"),
    ClientError(422, None, "bad request", None),
])
def test_clean_failure_before_or_at_hl_is_not_ambiguous(venue, exc):
    v, fake, _, _ = venue
    fake.exc = exc
    out = v.market("BTC", True, 1.0, 100.0)
    assert out["ok"] is False and out["ambiguous"] is False


def test_hl_rejection_status_is_not_ambiguous(venue):
    v, fake, _, _ = venue
    fake.result = {"status": "ok", "response": {"data": {"statuses": [{"error": "Insufficient margin"}]}}}
    assert v.market("BTC", True, 1.0, 100.0) == {"ok": False, "error": "Insufficient margin", "ambiguous": False}


def test_top_level_err_is_not_ambiguous(venue):
    v, fake, _, _ = venue
    fake.result = {"status": "err", "response": "User or API Wallet does not exist."}
    out = v.market("BTC", True, 1.0, 100.0)
    assert out == {"ok": False, "error": "User or API Wallet does not exist.", "ambiguous": False}


def test_ok_without_statuses_is_ambiguous(venue):
    v, fake, _, _ = venue
    fake.result = {"status": "ok", "response": {"data": {"statuses": []}}}
    out = v.market("BTC", True, 1.0, 100.0)
    assert out["ok"] is False and out["ambiguous"] is True


def test_get_exchange_failure_is_not_ambiguous(venue, monkeypatch):
    v, _, _, _ = venue

    def boom():
        raise RuntimeError("meta read timed out during Exchange construction")

    monkeypatch.setattr(sdk, "get_exchange", boom)
    out = v.market("BTC", True, 1.0, 100.0)
    assert out["ok"] is False and out["ambiguous"] is False


# ── 3. partial fills ─────────────────────────────────────────────────────────

def test_full_fill_ok_with_size_and_price(venue):
    v, _, _, _ = venue
    assert v.market("BTC", True, 1.0, 100.0) == {"ok": True, "ambiguous": False,
                                                  "filled_sz": 1.0, "avg_px": 100.5,
                                                  "oid": 77}   # oid: realized PnL from our fills


def test_partial_fill_is_not_ok_but_reports_filled_size(venue):
    v, fake, _, _ = venue
    fake.result = _filled(total_sz="0.4", avg_px="100.2")
    out = v.market("BTC", True, 1.0, 100.0)
    assert out["ok"] is False
    assert out["filled_sz"] == 0.4 and out["avg_px"] == 100.2
    assert "partial fill" in out["error"]
    assert out["ambiguous"] is False


def test_fill_within_half_a_size_tick_counts_as_full(venue):
    v, fake, _, _ = venue
    fake.result = _filled(total_sz="0.996")   # sz_decimals=2: tick 0.01, tolerance 0.005
    assert v.market("BTC", True, 1.0, 100.0)["ok"] is True
    fake.result = _filled(total_sz="0.99")    # one full tick short is partial
    assert v.market("BTC", True, 1.0, 100.0)["ok"] is False


def test_order_result_resting_gtc_is_ok():
    out = venue_mod._order_result({"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}},
                                  requested_sz=1.0, sz_dec=2)
    assert out["ok"] is True and out["filled_sz"] == 0.0


def test_order_result_unreadable_fill_is_ambiguous():
    out = venue_mod._order_result({"status": "ok", "response": {"data": {"statuses": [{"filled": {"oid": 1}}]}}},
                                  requested_sz=1.0, sz_dec=2)
    assert out["ok"] is False and out["ambiguous"] is True


# ── 4. reduce_only never bumped to the $10 floor ─────────────────────────────

def test_reduce_only_is_never_bumped_to_the_floor(venue):
    v, fake, _, _ = venue
    v.market("BTC", False, 0.05, 100.0, reduce_only=True)    # $5 residual
    assert fake.calls[0]["sz"] == 0.05
    assert fake.calls[0]["reduce_only"] is True


def test_open_is_still_bumped_to_the_floor(venue):
    v, fake, _, _ = venue
    v.market("BTC", True, 0.05, 100.0)
    assert fake.calls[0]["sz"] * 100.0 >= sizing.MIN_ORDER_USD


def test_size_rounding_to_zero_refused(venue):
    v, fake, _, _ = venue
    out = v.market("BTC", False, 0.001, 100.0, reduce_only=True)  # rounds to 0.00 at 2 dp
    assert out["ok"] is False and fake.calls == []


# ── 5. slippage cap ──────────────────────────────────────────────────────────

def test_buy_limit_is_capped_at_mid_plus_slippage(venue):
    v, fake, _, _ = venue
    v.market("BTC", True, 1.0, 100.0)                  # default 1%
    assert fake.calls[0]["px"] <= 101.0
    assert fake.calls[0]["px"] >= 100.1                # still crosses the ask


def test_sell_limit_is_capped_at_mid_minus_slippage(venue):
    v, fake, _, _ = venue
    v.market("BTC", False, 1.0, 100.0, max_slippage_pct=0.5)
    assert 99.5 <= fake.calls[0]["px"] <= 99.9


def test_cap_rounding_never_exceeds_the_cap(venue):
    """mid 123.456 * 1.01 = 124.69056: the old buy-side CEILING rounding gave
    124.70, past the cap. Rounding must go inward."""
    v, fake, _, book = venue
    book["v"] = _book(123.4, 123.5)
    v.market("BTC", True, 1.0, 123.456)
    assert fake.calls[0]["px"] <= 123.456 * 1.01


def test_touch_past_cap_buy_is_refused_without_sending(venue):
    v, fake, _, book = venue
    book["v"] = _book(99.0, 101.5)                     # ask already 1.5% over mid
    out = v.market("BTC", True, 1.0, 100.0)
    assert out == {"ok": False, "error": "slippage cap", "ambiguous": False}
    assert fake.calls == []


def test_touch_past_cap_sell_is_refused_without_sending(venue):
    v, fake, _, book = venue
    book["v"] = _book(98.0, 101.0)                     # bid 2% under mid
    out = v.market("BTC", False, 1.0, 100.0, max_slippage_pct=1.0)
    assert out["error"] == "slippage cap" and fake.calls == []


def test_wider_cap_lets_the_same_book_through(venue):
    v, fake, _, book = venue
    book["v"] = _book(99.0, 101.5)
    assert v.market("BTC", True, 1.0, 100.0, max_slippage_pct=2.0)["ok"] is True
    assert 101.5 <= fake.calls[0]["px"] <= 102.0


def test_no_book_still_sends_at_the_cap(venue):
    v, fake, _, book = venue
    book["v"] = None                                   # l2Book read failed
    assert v.market("BTC", True, 1.0, 100.0)["ok"] is True
    assert 100.0 < fake.calls[0]["px"] <= 101.0


def test_invalid_slippage_refused(venue):
    v, fake, _, _ = venue
    assert v.market("BTC", True, 1.0, 100.0, max_slippage_pct=0)["ok"] is False
    assert fake.calls == []


# ── close: confirmed by a fresh read ─────────────────────────────────────────

class _Positions:
    """account_state stub driven by a list of szi values, one per read
    (None = failed read). Records how many reads happened."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.reads = 0

    def __call__(self, _self, user):
        szi = self.sequence[min(self.reads, len(self.sequence) - 1)]
        self.reads += 1
        if szi is None:
            return None
        raw = {} if szi == 0 else {"BTC": {"szi": str(szi)}}
        return {"equity_perp_usd": 0.0, "spot_usdc": 0.0, "positions": {}, "available": {}, "raw_positions": raw}


@pytest.fixture
def closing(venue, monkeypatch):
    v, fake, _, _ = venue
    monkeypatch.setattr(HlVenue, "mid", lambda self, coin: 100.0)

    def use(sequence):
        stub = _Positions(sequence)
        monkeypatch.setattr(HlVenue, "account_state", lambda self, user, also_dexes=None: stub(self, user))
        return stub

    return v, fake, use


def test_close_already_flat_sends_nothing(closing):
    v, fake, use = closing
    use([0])
    assert v.close("BTC") == {"ok": True, "filled_sz": 0.0}
    assert fake.calls == []


def test_close_long_sells_reduce_only_with_cloid_and_confirms_flat(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="2.0", avg_px="99.95")
    stub = use([2.0, 0])
    out = v.close("BTC", cloid=CLOID)
    assert out == {"ok": True, "filled_sz": 2.0, "avg_px": 99.95, "oid": 77}   # oid: realized PnL from our fills
    c = fake.calls[0]
    assert c["is_buy"] is False and c["sz"] == 2.0 and c["reduce_only"] is True
    assert c["cloid"].to_raw() == CLOID
    assert stub.reads == 2   # sized from one read, confirmed by a fresh one


def test_close_short_buys_back(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="3.0")
    use([-3.0, 0])
    assert v.close("BTC")["ok"] is True
    assert fake.calls[0]["is_buy"] is True and fake.calls[0]["sz"] == 3.0


def test_close_partial_fill_is_not_ok_and_retry_closes_the_remainder(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="1.5")
    use([2.0, 0.5, 0.5, 0])
    first = v.close("BTC")
    assert first["ok"] is False and first["filled_sz"] == 1.5
    fake.result = _filled(total_sz="0.5")
    second = v.close("BTC")                            # retry re-reads: sends 0.5, not 2.0
    assert second["ok"] is True
    assert fake.calls[1]["sz"] == 0.5


def test_close_full_fill_but_position_still_open_is_not_ok(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="2.0")
    use([2.0, 2.0])                                    # fresh read disagrees with the fill
    out = v.close("BTC")
    assert out["ok"] is False and "not flat" in out["error"]


def test_close_post_read_failure_is_not_ok(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="2.0")
    use([2.0, None])
    out = v.close("BTC")
    assert out["ok"] is False and "post-close read failed" in out["error"]
    assert out["filled_sz"] == 2.0


def test_close_ambiguous_order_resolved_by_fresh_read(closing):
    v, fake, use = closing
    fake.exc = requests.exceptions.ReadTimeout("read timed out")
    use([2.0, 0])                                      # the order did land
    out = v.close("BTC")
    assert out["ok"] is True and "ambiguous" not in out


def test_close_ambiguous_and_still_open_stays_ambiguous(closing):
    v, fake, use = closing
    fake.exc = requests.exceptions.ReadTimeout("read timed out")
    use([2.0, 2.0])
    out = v.close("BTC")
    assert out["ok"] is False and out["ambiguous"] is True


def test_close_sub_10_dollar_residual_not_bumped(closing):
    v, fake, use = closing
    fake.result = _filled(total_sz="0.05")
    use([0.05, 0])                                     # $5 at mid 100
    assert v.close("BTC")["ok"] is True
    assert fake.calls[0]["sz"] == 0.05


def test_close_slippage_cap_env(closing, monkeypatch):
    v, fake, use = closing
    monkeypatch.setenv("COPYCAT_HL_CLOSE_SLIPPAGE_PCT", "3")
    fake.result = _filled(total_sz="2.0")
    use([2.0, 0])
    v.close("BTC")
    assert 97.0 <= fake.calls[0]["px"] < 99.9


def test_close_refuses_without_keys():
    out = HlVenue().close("BTC")
    assert out["ok"] is False and "COPYCAT_AGENT_KEY" in out["error"]


def test_market_refuses_without_keys():
    out = HlVenue().market("BTC", True, 1.0, 100.0, cloid=CLOID)
    assert out["ok"] is False and "COPYCAT_AGENT_KEY" in out["error"]


# ── 6. Exchange construction: bounded, lock not held ─────────────────────────

class _FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append(kw)
        return "ok"


def test_exchange_gets_timeout_and_both_sessions_guarded(write_creds, monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_TIMEOUT_S", "6.5")
    monkeypatch.setattr(sdk, "_perp_dexs_arg", lambda: None)
    built = {}

    class _FakeInfo:
        def __init__(self):
            self.session = _FakeSession()

    class _FakeEx:
        def __init__(self, **kw):
            built.update(kw)
            # the constructor's own reads run with the singleton lock free
            assert sdk._lock.acquire(blocking=False)
            sdk._lock.release()
            self.session = _FakeSession()
            self.info = _FakeInfo()

    monkeypatch.setattr(sdk, "Exchange", _FakeEx)
    ex = sdk.get_exchange()
    assert built["timeout"] == 6.5
    ex.session.request("POST", "u", timeout=None)
    ex.info.session.request("POST", "u", timeout=None)
    assert ex.session.calls[-1]["timeout"] == 6.5
    assert ex.info.session.calls[-1]["timeout"] == 6.5
    assert sdk.get_exchange() is ex   # cached


# ── 7. main-wallet key guard ─────────────────────────────────────────────────

def test_main_wallet_key_is_refused(monkeypatch):
    key = "0x" + "33" * 32
    monkeypatch.setenv("COPYCAT_AGENT_KEY", key)
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", Account.from_key(key).address.lower())
    monkeypatch.setattr(sdk, "Exchange", lambda **kw: pytest.fail("must not construct an Exchange"))
    with pytest.raises(sdk.MainWalletKeyError):
        sdk.get_exchange()


def test_main_wallet_key_surfaces_as_ok_false_with_instructions(monkeypatch):
    key = "0x" + "33" * 32
    monkeypatch.setenv("COPYCAT_AGENT_KEY", key)
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", Account.from_key(key).address)
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 2)
    monkeypatch.setattr(venue_mod, "http_post", lambda path, payload, **kw: _book(99.9, 100.1))
    v = HlVenue()
    for out in (v.market("BTC", True, 1.0, 100.0), v.set_leverage("BTC", 5, True)):
        assert out["ok"] is False
        assert "app.hyperliquid.xyz/API" in out["error"]


def test_agent_key_different_from_account_passes_check():
    assert sdk.check_agent_key("0x" + "11" * 32, ACCOUNT) is None
    assert "not a valid private key" in sdk.check_agent_key("0xzz", ACCOUNT)
