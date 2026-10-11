"""A deterministic, offline, stateful mock of Hyperliquid for the e2e lane.

The whole stack runs against it through COPYCAT_HL_BASE_URL (services/hl/hl/env.py):

  POST /info                   every /info type copycat sends (HL's real shapes)
  POST /exchange               orders, leverage, approveAgent, usdSend, withdraw3, usdClassTransfer.
                               L1 actions are signature-checked: the signer must be an agent the
                               account approved (extraAgents), exactly like HL. Every request is
                               RECORDED, decoded (coin, side, size, price, reduce-only, tif,
                               leverage, isolated) so a test can assert which orders the engine sent.
  GET  /{Mainnet,Testnet}/leaderboard   the stats-data leaderboard

Control plane for the tests (never something copycat calls):

  GET  /__mock/health
  POST /__mock/reset           back to the fixture state, recordings cleared
  POST /__mock/user            upsert an account: {address, cash?, positions?, agents?, abstraction?, spot_usdc?}
                               positions: {coin: {szi, entryPx?, leverage?, isCross?}}; szi 0 removes it
  POST /__mock/mids            {coin: px}
  POST /__mock/fail            {kind: "order", times: n, error: "..."}: next n orders rejected
  GET  /__mock/exchange        recorded /exchange requests (decoded), ?since=<seq>
  GET  /__mock/state           the whole state (debug)

Fills are deterministic: an IOC order fills in full at the coin's mid when its limit
price crosses the mid, else it is rejected the way HL rejects an IOC that cannot match.
Signing on a non-mainnet base URL uses the SDK's testnet phantom-agent source, so the
recovery here tries testnet first. Nothing in this file ever talks to the network.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from hyperliquid.utils.signing import (
    recover_agent_or_user_from_l1_action,
    recover_user_from_user_signed_action,
)

# ── fixtures ─────────────────────────────────────────────────────────────────

MARKETS: List[Dict[str, Any]] = [
    {"name": "BTC", "szDecimals": 5, "maxLeverage": 40, "mid": 100000.0},
    {"name": "ETH", "szDecimals": 4, "maxLeverage": 25, "mid": 4000.0},
    {"name": "SOL", "szDecimals": 2, "maxLeverage": 20, "mid": 200.0},
    {"name": "HYPE", "szDecimals": 2, "maxLeverage": 10, "mid": 40.0, "onlyIsolated": True},
]

# Leaders known to the leaderboard. Addresses are made up (never a real wallet).
LEADERS: List[Dict[str, Any]] = [
    {"address": "0x1111111111111111111111111111111111111111", "name": "mock-alpha", "cash": 250000.0},
    {"address": "0x2222222222222222222222222222222222222222", "name": "mock-beta", "cash": 120000.0},
    {"address": "0x3333333333333333333333333333333333333333", "name": "mock-gamma", "cash": 80000.0},
]

USER_SIGNED_TYPES = {
    "approveAgent": ("HyperliquidTransaction:ApproveAgent", [
        {"name": "hyperliquidChain", "type": "string"}, {"name": "agentAddress", "type": "address"},
        {"name": "agentName", "type": "string"}, {"name": "nonce", "type": "uint64"}]),
    "usdSend": ("HyperliquidTransaction:UsdSend", [
        {"name": "hyperliquidChain", "type": "string"}, {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"}, {"name": "time", "type": "uint64"}]),
    "withdraw3": ("HyperliquidTransaction:Withdraw", [
        {"name": "hyperliquidChain", "type": "string"}, {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"}, {"name": "time", "type": "uint64"}]),
    "usdClassTransfer": ("HyperliquidTransaction:UsdClassTransfer", [
        {"name": "hyperliquidChain", "type": "string"}, {"name": "amount", "type": "string"},
        {"name": "toPerp", "type": "bool"}, {"name": "nonce", "type": "uint64"}]),
}

DAY_MS = 86_400_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt(x: float, dp: int = 6) -> str:
    s = f"{x:.{dp}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class State:
    """All mutable mock state, behind one lock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.markets: Dict[str, Dict[str, Any]] = {m["name"]: dict(m) for m in MARKETS}
            self.users: Dict[str, Dict[str, Any]] = {}
            self.exchange: List[Dict[str, Any]] = []
            self.info_counts: Dict[str, int] = {}
            self.fail_orders: List[str] = []
            self.seq = 0
            self.oid = 1000
            for lead in LEADERS:
                self.user(lead["address"])["cash"] = lead["cash"]

    # users ---------------------------------------------------------------
    def user(self, address: str) -> Dict[str, Any]:
        key = address.lower()
        u = self.users.get(key)
        if u is None:
            u = {"address": key, "cash": 0.0, "positions": {}, "agents": [], "abstraction": "default",
                 "spot_usdc": 0.0, "fills": [], "ledger": [], "leverage": {}, "orders": {}}
            self.users[key] = u
        return u

    def upsert_user(self, body: Dict[str, Any]) -> Dict[str, Any]:
        u = self.user(str(body["address"]))
        for k in ("cash", "spot_usdc"):
            if k in body:
                u[k] = float(body[k])
        if "abstraction" in body:
            u["abstraction"] = str(body["abstraction"])
        if "agents" in body:
            u["agents"] = [{"address": str(a["address"]).lower(), "name": str(a.get("name") or "e2e"),
                            "validUntil": int(a.get("validUntil") or (_now_ms() + 180 * DAY_MS))}
                           for a in body["agents"]]
        for coin, p in (body.get("positions") or {}).items():
            szi = float(p.get("szi") or 0)
            if szi == 0:
                u["positions"].pop(coin, None)
                continue
            mid = self.markets[coin]["mid"]
            prev = u["positions"].get(coin) or {}
            u["positions"][coin] = {
                "szi": szi,
                "entryPx": float(p.get("entryPx") or prev.get("entryPx") or mid),
                "leverage": int(p.get("leverage") or prev.get("leverage") or 5),
                "isCross": bool(p.get("isCross", prev.get("isCross", False))),
            }
        return u

    def agent_owner(self, agent: str) -> Optional[str]:
        a = agent.lower()
        for u in self.users.values():
            if any(x["address"] == a for x in u["agents"]):
                return u["address"]
        return None

    # accounting ------------------------------------------------------------
    def upnl(self, u: Dict[str, Any]) -> float:
        return sum(p["szi"] * (self.markets[c]["mid"] - p["entryPx"]) for c, p in u["positions"].items())

    def margin_used(self, u: Dict[str, Any]) -> float:
        return sum(abs(p["szi"]) * self.markets[c]["mid"] / max(1, p["leverage"])
                   for c, p in u["positions"].items())

    def account_value(self, u: Dict[str, Any]) -> float:
        return u["cash"] + self.upnl(u)

    def clearinghouse(self, address: str, dex: str) -> Dict[str, Any]:
        u = self.user(address)
        if dex:
            return {"marginSummary": {"accountValue": "0", "totalNtlPos": "0", "totalRawUsd": "0",
                                      "totalMarginUsed": "0"},
                    "crossMarginSummary": {"accountValue": "0", "totalNtlPos": "0", "totalRawUsd": "0",
                                           "totalMarginUsed": "0"},
                    "crossMaintenanceMarginUsed": "0", "withdrawable": "0", "assetPositions": [],
                    "time": _now_ms()}
        av = self.account_value(u)
        used = self.margin_used(u)
        ntl = sum(abs(p["szi"]) * self.markets[c]["mid"] for c, p in u["positions"].items())
        aps = []
        for coin, p in sorted(u["positions"].items()):
            mid = self.markets[coin]["mid"]
            pv = abs(p["szi"]) * mid
            margin = pv / max(1, p["leverage"])
            upnl = p["szi"] * (mid - p["entryPx"])
            liq = p["entryPx"] * (1 - 1 / p["leverage"]) if p["szi"] > 0 else p["entryPx"] * (1 + 1 / p["leverage"])
            aps.append({"type": "oneWay", "position": {
                "coin": coin, "szi": _fmt(p["szi"], 8), "entryPx": _fmt(p["entryPx"]),
                "leverage": {"type": "cross" if p["isCross"] else "isolated", "value": p["leverage"],
                             **({} if p["isCross"] else {"rawUsd": _fmt(-p["szi"] * p["entryPx"] + margin)})},
                "positionValue": _fmt(pv), "unrealizedPnl": _fmt(upnl),
                "returnOnEquity": _fmt(upnl / margin if margin else 0), "liquidationPx": _fmt(liq),
                "marginUsed": _fmt(margin), "maxLeverage": self.markets[coin]["maxLeverage"],
                "cumFunding": {"allTime": "0", "sinceOpen": "0", "sinceChange": "0"}}})
        summary = {"accountValue": _fmt(av), "totalNtlPos": _fmt(ntl), "totalRawUsd": _fmt(u["cash"]),
                   "totalMarginUsed": _fmt(used)}
        return {"marginSummary": summary, "crossMarginSummary": dict(summary),
                "crossMaintenanceMarginUsed": _fmt(used / 2), "withdrawable": _fmt(max(0.0, av - used)),
                "assetPositions": aps, "time": _now_ms()}

    def fill(self, u: Dict[str, Any], coin: str, is_buy: bool, sz: float, px: float,
             reduce_only: bool, cloid: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        p = u["positions"].get(coin)
        szi = p["szi"] if p else 0.0
        if reduce_only:
            if szi == 0 or (szi > 0) == is_buy:
                return None, "Reduce only order would increase position. asset=0"
            sz = min(sz, abs(szi))
        delta = sz if is_buy else -sz
        new = round(szi + delta, 10)
        closed_pnl = 0.0
        lev_conf = u["leverage"].get(coin) or {"leverage": (p or {}).get("leverage", 20), "isCross": True}
        if p is None or szi == 0:
            u["positions"][coin] = {"szi": new, "entryPx": px, "leverage": lev_conf["leverage"],
                                    "isCross": lev_conf["isCross"]}
            direction = "Open Long" if is_buy else "Open Short"
        elif (szi > 0) == is_buy:   # add
            p["entryPx"] = (abs(szi) * p["entryPx"] + sz * px) / (abs(szi) + sz)
            p["szi"] = new
            direction = "Open Long" if is_buy else "Open Short"
        else:                        # reduce / close / flip
            closed = min(abs(szi), sz)
            closed_pnl = closed * (px - p["entryPx"]) * (1 if szi > 0 else -1)
            u["cash"] += closed_pnl
            direction = "Close Long" if szi > 0 else "Close Short"
            if abs(new) < 1e-12:
                u["positions"].pop(coin, None)
            elif (new > 0) != (szi > 0):
                u["positions"][coin] = {"szi": new, "entryPx": px, "leverage": p["leverage"],
                                        "isCross": p["isCross"]}
            else:
                p["szi"] = new
        fee = sz * px * 0.00045
        u["cash"] -= fee
        self.oid += 1
        f = {"coin": coin, "px": _fmt(px), "sz": _fmt(sz, 8), "side": "B" if is_buy else "A",
             "time": _now_ms(), "startPosition": _fmt(szi, 8), "dir": direction,
             "closedPnl": _fmt(closed_pnl), "hash": "0x" + f"{self.oid:064x}", "oid": self.oid,
             "crossed": True, "fee": _fmt(fee), "tid": self.oid, "feeToken": "USDC"}
        u["fills"].append(f)
        if cloid:
            u["orders"][cloid.lower()] = {"oid": self.oid, "status": "filled", "coin": coin,
                                          "side": f["side"], "sz": f["sz"], "px": f["px"]}
        return f, None


STATE = State()


# ── /info ────────────────────────────────────────────────────────────────────

def _meta() -> Dict[str, Any]:
    uni = []
    for m in STATE.markets.values():
        e = {"name": m["name"], "szDecimals": m["szDecimals"], "maxLeverage": m["maxLeverage"],
             "marginTableId": m["maxLeverage"]}
        if m.get("onlyIsolated"):
            e["onlyIsolated"] = True
        uni.append(e)
    return {"universe": uni, "marginTables": []}


def _asset_ctx(m: Dict[str, Any]) -> Dict[str, Any]:
    mid = m["mid"]
    return {"funding": "0.0000125", "openInterest": _fmt(5_000_000 / mid), "prevDayPx": _fmt(mid * 0.99),
            "dayNtlVlm": "500000000", "premium": "0", "oraclePx": _fmt(mid), "markPx": _fmt(mid),
            "midPx": _fmt(mid), "impactPxs": [_fmt(mid * 0.9999), _fmt(mid * 1.0001)],
            "dayBaseVlm": _fmt(500_000_000 / mid)}


def _l2(coin: str) -> Dict[str, Any]:
    m = STATE.markets[coin]
    mid, tick = m["mid"], m["mid"] * 0.0001
    lvl = lambda px: {"px": _fmt(px), "sz": _fmt(2_000_000 / mid, 4), "n": 5}
    return {"coin": coin, "time": _now_ms(),
            "levels": [[lvl(mid - tick * (i + 1)) for i in range(20)], [lvl(mid + tick * (i + 1)) for i in range(20)]]}


def _candles(req: Dict[str, Any]) -> List[Dict[str, Any]]:
    coin = req.get("coin", "BTC")
    m = STATE.markets.get(coin) or STATE.markets["BTC"]
    step = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
            "1d": DAY_MS}.get(req.get("interval", "1h"), 3_600_000)
    start, end = int(req.get("startTime", 0)), int(req.get("endTime", _now_ms()))
    t = start - start % step
    out = []
    while t <= end and len(out) < 5000:
        c = m["mid"] * (1 + 0.02 * math.sin(t / (step * 24)))
        o = m["mid"] * (1 + 0.02 * math.sin((t - step) / (step * 24)))
        out.append({"t": t, "T": t + step - 1, "s": coin, "i": req.get("interval", "1h"), "o": _fmt(o),
                    "c": _fmt(c), "h": _fmt(max(o, c) * 1.002), "l": _fmt(min(o, c) * 0.998),
                    "v": "100", "n": 10})
        t += step
    return out


def _portfolio(address: str) -> List[Any]:
    u = STATE.user(address)
    av = STATE.account_value(u)
    now = _now_ms()
    out = []
    for label, span in (("day", DAY_MS), ("week", 7 * DAY_MS), ("month", 30 * DAY_MS), ("allTime", 90 * DAY_MS)):
        pts = [now - span + i * span // 10 for i in range(11)]
        hist = {"accountValueHistory": [[t, _fmt(av * (0.9 + 0.01 * i))] for i, t in enumerate(pts)],
                "pnlHistory": [[t, _fmt(av * 0.01 * i)] for i, t in enumerate(pts)], "vlm": "1000"}
        out.append([label, hist])
        out.append(["perp" + label[0].upper() + label[1:], hist])
    return out


def info(body: Dict[str, Any]) -> Any:
    t = body.get("type")
    with STATE.lock:
        STATE.info_counts[t] = STATE.info_counts.get(t, 0) + 1
        user = str(body.get("user") or "")
        if t == "meta":
            return _meta() if not body.get("dex") else {"universe": [], "marginTables": []}
        if t == "metaAndAssetCtxs":
            if body.get("dex"):
                return [{"universe": [], "marginTables": []}, []]
            return [_meta(), [_asset_ctx(m) for m in STATE.markets.values()]]
        if t == "spotMeta":
            return {"tokens": [{"name": "USDC", "szDecimals": 8, "weiDecimals": 8, "index": 0,
                                "tokenId": "0x6d1e7cde53ba9467b783cb7c530ce054", "isCanonical": True,
                                "evmContract": None, "fullName": None}], "universe": []}
        if t == "spotMetaAndAssetCtxs":
            return [info({"type": "spotMeta"}), []]
        if t == "perpDexs":
            return [None]
        if t == "allMids":
            return {} if body.get("dex") else {c: _fmt(m["mid"]) for c, m in STATE.markets.items()}
        if t == "l2Book":
            coin = body.get("coin")
            return _l2(coin) if coin in STATE.markets else None
        if t == "clearinghouseState":
            return STATE.clearinghouse(user, str(body.get("dex") or ""))
        if t == "spotClearinghouseState":
            u = STATE.user(user)
            return {"balances": [{"coin": "USDC", "token": 0, "hold": "0", "total": _fmt(u["spot_usdc"]),
                                  "entryNtl": "0"}]}
        if t == "userAbstraction":
            return STATE.user(user)["abstraction"]
        if t == "extraAgents":
            return copy.deepcopy(STATE.user(user)["agents"])
        if t == "delegatorSummary":
            return {"delegated": "0", "undelegated": "0", "totalPendingWithdrawal": "0", "nPendingWithdrawals": 0}
        if t == "userNonFundingLedgerUpdates":
            start = int(body.get("startTime") or 0)
            return [r for r in STATE.user(user)["ledger"] if r["time"] >= start]
        if t in ("userFills", "userFillsByTime"):
            start = int(body.get("startTime") or 0)
            end = int(body.get("endTime") or 2 ** 62)
            fills = [f for f in STATE.user(user)["fills"] if start <= f["time"] <= end]
            return sorted(fills, key=lambda f: f["time"])
        if t in ("frontendOpenOrders", "openOrders", "historicalOrders"):
            return []
        if t == "orderStatus":
            o = STATE.user(user)["orders"].get(str(body.get("oid") or "").lower())
            if not o:
                return {"status": "unknownOid"}
            return {"status": "order", "order": {"order": {"coin": o["coin"], "side": o["side"], "limitPx": o["px"],
                                                           "sz": "0", "oid": o["oid"], "timestamp": _now_ms(),
                                                           "origSz": o["sz"]},
                                                 "status": o["status"], "statusTimestamp": _now_ms()}}
        if t == "portfolio":
            return _portfolio(user)
        if t == "candleSnapshot":
            return _candles(body.get("req") or {})
        if t in ("userFees", "userRateLimit", "subAccounts", "vaultDetails", "userVaultEquities",
                 "userTwapSliceFills", "userFunding"):
            return [] if t != "userRateLimit" else {"cumVlm": "0", "nRequestsUsed": 0, "nRequestsCap": 10000}
    return None   # unknown type: HL answers 422; the caller sees a failed read


# ── /exchange ────────────────────────────────────────────────────────────────

def _recover_l1(body: Dict[str, Any]) -> Optional[str]:
    for is_mainnet in (False, True):
        try:
            addr = recover_agent_or_user_from_l1_action(
                body["action"], body["signature"], body.get("vaultAddress"), int(body["nonce"]),
                body.get("expiresAfter"), is_mainnet)
        except Exception:
            continue
        if addr and (STATE.agent_owner(addr) or addr.lower() in STATE.users):
            return addr.lower()
    return None


def _recover_user_signed(action: Dict[str, Any], sig: Dict[str, Any]) -> Optional[str]:
    primary, types = USER_SIGNED_TYPES[action["type"]]
    try:
        return recover_user_from_user_signed_action(
            dict(action), sig, types, primary, action.get("hyperliquidChain") == "Mainnet").lower()
    except Exception:
        return None


def exchange(body: Dict[str, Any]) -> Dict[str, Any]:
    action = body.get("action") or {}
    atype = action.get("type")
    with STATE.lock:
        STATE.seq += 1
        rec: Dict[str, Any] = {"seq": STATE.seq, "time": _now_ms(), "type": atype, "action": action,
                               "nonce": body.get("nonce"), "vaultAddress": body.get("vaultAddress")}
        STATE.exchange.append(rec)
        resp = _exchange_locked(atype, action, body, rec)
        rec["response"] = resp
        return resp


def _err(msg: str) -> Dict[str, Any]:
    return {"status": "err", "response": msg}


def _exchange_locked(atype: Any, action: Dict[str, Any], body: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    if atype in USER_SIGNED_TYPES:
        signer = _recover_user_signed(action, body.get("signature") or {})
        rec["signer"] = signer
        if not signer:
            return _err("invalid signature")
        u = STATE.user(signer)
        rec["user"] = signer
        if atype == "approveAgent":
            agent = str(action.get("agentAddress") or "").lower()
            u["agents"] = [a for a in u["agents"] if a["address"] != agent] + [
                {"address": agent, "name": str(action.get("agentName") or ""),
                 "validUntil": _now_ms() + 180 * DAY_MS}]
            rec["agent"] = agent
            return {"status": "ok", "response": {"type": "default"}}
        amount = float(action.get("amount") or 0)
        rec["amount"] = amount
        if atype == "usdClassTransfer":
            if action.get("toPerp"):
                if amount > u["spot_usdc"]:
                    return _err("Insufficient balance")
                u["spot_usdc"] -= amount
                u["cash"] += amount
            else:
                u["cash"] -= amount
                u["spot_usdc"] += amount
        elif atype in ("usdSend", "withdraw3"):
            withdrawable = STATE.account_value(u) - STATE.margin_used(u)
            if amount > withdrawable:
                return _err("Insufficient balance for withdrawal")
            u["cash"] -= amount
            dest = str(action.get("destination") or "").lower()
            rec["destination"] = dest
            if atype == "usdSend":
                STATE.user(dest)["cash"] += amount
        u["ledger"].append({"time": _now_ms(), "hash": "0x" + f"{STATE.seq:064x}",
                            "delta": {"type": {"usdSend": "send", "withdraw3": "withdraw",
                                               "usdClassTransfer": "accountClassTransfer"}[atype],
                                      "usdc": _fmt(amount)}})
        return {"status": "ok", "response": {"type": "default"}}

    signer = _recover_l1(body)
    rec["signer"] = signer
    owner = STATE.agent_owner(signer) if signer else None
    if not owner:
        return _err(f"User or API Wallet {signer} does not exist.")
    u = STATE.user(owner)
    rec["user"] = owner
    names = list(STATE.markets)
    if atype == "updateLeverage":
        coin = names[int(action["asset"])]
        lev = int(action["leverage"])
        is_cross = bool(action["isCross"])
        rec.update(coin=coin, leverage=lev, is_cross=is_cross)
        m = STATE.markets[coin]
        if lev > m["maxLeverage"]:
            return _err(f"Invalid leverage value. asset={action['asset']}")
        if is_cross and m.get("onlyIsolated"):
            return _err("Cross margin is not allowed for this asset.")
        u["leverage"][coin] = {"leverage": lev, "isCross": is_cross}
        if coin in u["positions"]:
            u["positions"][coin]["leverage"] = lev
            u["positions"][coin]["isCross"] = is_cross
        return {"status": "ok", "response": {"type": "default"}}
    if atype == "order":
        statuses = []
        rec["orders"] = []
        for o in action.get("orders") or []:
            coin = names[int(o["a"])]
            is_buy, sz, px = bool(o["b"]), float(o["s"]), float(o["p"])
            tif = ((o.get("t") or {}).get("limit") or {}).get("tif")
            lev_conf = u["leverage"].get(coin) or {}
            d = {"coin": coin, "is_buy": is_buy, "side": "buy" if is_buy else "sell", "sz": sz, "px": px,
                 "reduce_only": bool(o.get("r")), "tif": tif, "cloid": o.get("c"),
                 "leverage": lev_conf.get("leverage"), "is_cross": lev_conf.get("isCross")}
            rec["orders"].append(d)
            mid = STATE.markets[coin]["mid"]
            if STATE.fail_orders:
                d["error"] = STATE.fail_orders.pop(0)
                statuses.append({"error": d["error"]})
                continue
            if (is_buy and px < mid) or (not is_buy and px > mid):
                d["error"] = "ioc no match"
                statuses.append({"error": f"Order could not immediately match against any resting orders. asset={o['a']}"})
                continue
            if not o.get("r") and sz * mid < 10:
                d["error"] = "min value"
                statuses.append({"error": "Order must have minimum value of $10."})
                continue
            f, err = STATE.fill(u, coin, is_buy, sz, mid, bool(o.get("r")), o.get("c"))
            if err:
                d["error"] = err
                statuses.append({"error": err})
                continue
            d["filled_sz"] = float(f["sz"])
            statuses.append({"filled": {"totalSz": f["sz"], "avgPx": f["px"], "oid": f["oid"]}})
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": statuses}}}
    if atype == "cancel" or atype == "cancelByCloid":
        return {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}
    return _err(f"mock: unsupported action {atype}")


# ── control plane ────────────────────────────────────────────────────────────

def leaderboard() -> Dict[str, Any]:
    rows = []
    with STATE.lock:
        for i, lead in enumerate(LEADERS):
            u = STATE.user(lead["address"])
            av = STATE.account_value(u)
            perf = lambda mult: {"pnl": _fmt(av * 0.01 * mult), "roi": _fmt(0.01 * mult),
                                 "vlm": _fmt(5_000_000 * mult)}
            rows.append({"ethAddress": lead["address"], "accountValue": _fmt(av),
                         "windowPerformances": [["day", perf(1)], ["week", perf(3)], ["month", perf(10)],
                                                ["allTime", perf(40 - i)]],
                         "prize": 0, "displayName": lead["name"]})
    return {"leaderboardRows": rows}


def control(method: str, path: str, query: Dict[str, List[str]], body: Any) -> Tuple[int, Any]:
    with STATE.lock:
        if path == "/__mock/health":
            return 200, {"ok": True}
        if path == "/__mock/reset" and method == "POST":
            STATE.reset()
            return 200, {"ok": True}
        if path == "/__mock/user" and method == "POST":
            u = STATE.upsert_user(body or {})
            return 200, {"address": u["address"], "accountValue": STATE.account_value(u),
                         "positions": u["positions"]}
        if path == "/__mock/mids" and method == "POST":
            for coin, px in (body or {}).items():
                STATE.markets[coin]["mid"] = float(px)
            return 200, {c: m["mid"] for c, m in STATE.markets.items()}
        if path == "/__mock/fail" and method == "POST":
            STATE.fail_orders.extend([str(body.get("error") or "mock rejected")] * int(body.get("times") or 1))
            return 200, {"pending": len(STATE.fail_orders)}
        if path == "/__mock/exchange":
            since = int((query.get("since") or ["0"])[0])
            return 200, [r for r in STATE.exchange if r["seq"] > since]
        if path == "/__mock/state":
            return 200, {"users": STATE.users, "markets": STATE.markets, "info_counts": STATE.info_counts,
                         "exchange_count": len(STATE.exchange)}
    return 404, {"error": f"unknown control route {method} {path}"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:   # quiet; the recording is the log
        return

    def _send(self, code: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> Any:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else None

    def do_GET(self) -> None:
        u = urlsplit(self.path)
        if u.path in ("/Mainnet/leaderboard", "/Testnet/leaderboard"):
            return self._send(200, leaderboard())
        code, payload = control("GET", u.path, parse_qs(u.query), None)
        self._send(code, payload)

    def do_POST(self) -> None:
        u = urlsplit(self.path)
        try:
            body = self._body()
        except Exception:
            return self._send(400, {"error": "bad json"})
        if u.path == "/info":
            out = info(body or {})
            if out is None and (body or {}).get("type") not in ("l2Book",):
                return self._send(422, {"error": f"mock: unsupported info type {(body or {}).get('type')}"})
            return self._send(200, out)
        if u.path == "/exchange":
            return self._send(200, exchange(body or {}))
        code, payload = control("POST", u.path, parse_qs(u.query), body)
        self._send(code, payload)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--port-file", help="write the bound port here once listening")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    if args.port_file:
        with open(args.port_file, "w") as f:
            f.write(str(port))
    print(f"mock hyperliquid listening on http://127.0.0.1:{port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
