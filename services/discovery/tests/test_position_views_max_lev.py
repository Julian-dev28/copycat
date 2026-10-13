"""Audit S8: trader positions carry HL's coin max leverage so the web's local
ticket estimate can cap target leverage the way the engine does."""
from discovery.scout import metrics as M


def test_position_views_carry_max_leverage():
    v = M.position_views({"BTC": {"szi": "1", "positionValue": "100", "entryPx": "100",
                                  "leverage": {"type": "cross", "value": 5}, "maxLeverage": 40},
                          "ETH": {"szi": "-1", "positionValue": "50", "entryPx": "50",
                                  "leverage": {"type": "isolated", "value": 3}}})
    by = {p.coin: p for p in v}
    assert by["BTC"].max_leverage == 40 and by["ETH"].max_leverage is None
