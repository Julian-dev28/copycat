"""RealScoutClient against a stand-in `discovery.scout.public` module
(sys.modules, restored by monkeypatch), so the adapter is tested without
the real package: lazy import, ScoutUnavailable, ScoutBusy mapping,
dict/model coercion, and the background HL priority flip."""
from __future__ import annotations

import sys
import types

import pytest

from contracts.models import LeaderOverride, ScoutStatus, Settings, TraderProfile
from api.scout_client import RealScoutClient, ScoutBusy, ScoutUnavailable

from api_fakes import ADDR_A, make_profile, make_row, make_score


class _Busy(RuntimeError):
    pass


def _install(monkeypatch: pytest.MonkeyPatch, **fns) -> types.ModuleType:
    public = types.ModuleType("discovery.scout.public")
    public.ScoutBusy = _Busy
    for k, v in fns.items():
        setattr(public, k, v)
    pkg = types.ModuleType("discovery.scout")
    pkg.public = public
    monkeypatch.setitem(sys.modules, "discovery.scout", pkg)
    monkeypatch.setitem(sys.modules, "discovery.scout.public", public)
    return public


def test_missing_package_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "discovery.scout", None)
    with pytest.raises(ScoutUnavailable):
        RealScoutClient().status()


def test_missing_function_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    with pytest.raises(ScoutUnavailable, match="scout_status"):
        RealScoutClient().status()


def test_busy_maps_to_scout_busy_other_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def refresh():
        raise _Busy("running")

    def status():
        raise ValueError("bug")

    _install(monkeypatch, scout_refresh=refresh, scout_status=status)
    with pytest.raises(ScoutBusy, match="running"):
        RealScoutClient().refresh()
    with pytest.raises(ValueError):           # a bug is a 500, never disguised as 409
        RealScoutClient().status()


def test_first_call_sets_background_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "engine")
    _install(monkeypatch, scout_status=lambda: {"refresh_id": None, "state": "idle"})
    assert RealScoutClient().status().state == "idle"
    import os
    assert os.environ["COPYCAT_HL_PRIORITY"] == "background"


def test_dicts_and_models_both_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    def page(query):
        calls["page"] = query
        return {"as_of_ms": 1, "refresh_id": "r", "settings_hash": "h", "cohort_size": 1, "total": 1,
                "rows": [make_row(ADDR_A).model_dump(mode="json")]}

    def what_if(address, settings, eq, override):
        calls["what_if"] = (address, settings, eq, override)
        return {"score": make_score(address), "sim_curve": []}

    _install(monkeypatch, scout_page=page, scout_what_if=what_if,
             scout_fills=lambda a, b, n: [{"time_ms": 1, "coin": "BTC", "side": "A", "dir": "Close Long",
                                           "px": 1, "sz": 1, "notional_usd": 1, "closed_pnl_usd": 0,
                                           "fee_usd": 0}],
             scout_orders=lambda a: [{"coin": "BTC", "side": "A", "limitPx": "100.5", "sz": "2",
                                      "origSz": "3", "oid": 1, "timestamp": 5, "reduceOnly": True,
                                      "orderType": "Take Profit Limit", "isTrigger": True,
                                      "triggerPx": "99", "triggerCondition": "Price below 99",
                                      "tif": None}],
             scout_presets=lambda: {"coins": ["BTC"], "coin_counts": {"BTC": 3}, "hip3_count": 1})
    c = RealScoutClient()
    assert c.page({"limit": 5}).rows[0].address == ADDR_A
    assert calls["page"] == {"limit": 5}
    s = Settings()
    o = LeaderOverride(leverage=2)
    assert c.what_if(ADDR_A, s, 100.0, o).score.address == ADDR_A
    assert calls["what_if"] == (ADDR_A, s, 100.0, o)
    assert c.fills(ADDR_A, None, 10)[0].side == "A"
    o = c.orders(ADDR_A)[0]
    assert (o.oid, o.side, o.limit_px, o.sz, o.orig_sz, o.notional_usd) == (1, "A", 100.5, 2.0, 3.0, 201.0)
    assert (o.reduce_only, o.is_trigger, o.trigger_px, o.time_ms) == (True, True, 99.0, 5)
    assert o.order_type == "Take Profit Limit" and o.trigger_condition == "Price below 99"
    p = c.presets()
    assert p.coin_counts == {"BTC": 3} and p.hip3_count == 1


def test_open_order_view_raw_hl_untriggered_and_contract_shape() -> None:
    from api.scout_client import open_order_view
    raw = {"coin": "ETH", "side": "B", "limitPx": "10", "sz": "1", "oid": 2, "timestamp": 9,
           "triggerPx": "0.0", "triggerCondition": "N/A", "isTrigger": False, "tif": "Gtc"}
    o = open_order_view(raw)
    assert o.trigger_px is None and o.trigger_condition is None and o.orig_sz == 1.0
    assert o.order_type == "Limit" and o.tif == "Gtc"
    assert open_order_view(o.model_dump()) == o          # contract-shaped dicts pass straight through


@pytest.mark.parametrize("ret,kind", [
    (None, type(None)),
    ("profile_model", TraderProfile),
    ("profile_dict", TraderProfile),
    ("status_model", ScoutStatus),
    ("status_dict", ScoutStatus),
])
def test_profile_shapes(monkeypatch: pytest.MonkeyPatch, ret, kind) -> None:
    values = {
        None: None,
        "profile_model": make_profile(ADDR_A),
        "profile_dict": make_profile(ADDR_A).model_dump(mode="json"),
        "status_model": ScoutStatus(refresh_id=None, state="running"),
        "status_dict": {"refresh_id": None, "state": "running", "stage": "stats"},
    }
    _install(monkeypatch, scout_profile=lambda a: values[ret])
    assert isinstance(RealScoutClient().profile(ADDR_A), kind)
