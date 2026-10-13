"""Runs every step of services/mcp/DEMO.md against a real api through the real
MCP server over stdio (no Claude, no cost) and checks what the doc promises.

Called by demo_check.sh, which boots a throwaway api first. Args:
  api_url admin_token mcp_token trader_address transcript_path

Each step prints one PASS/FAIL line; the exit code is the number of failures.
The transcript file gets every tool call and a short view of its result, so
the doc's "what you will see" blocks can be checked against a real run.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[3]
RUN_SH = ROOT / "services" / "mcp" / "run.sh"

READ_TOOLS = {"scout_list", "trader_profile", "trader_fingerprint", "trader_trades", "trader_fills",
              "market_candles", "list_theses", "save_thesis", "copycat_settings", "engine_status",
              "my_wallets", "preview_copy", "copy_plan"}


class Demo:
    def __init__(self, api: str, admin: str, mcp_token: str, trader: str, transcript: Path) -> None:
        self.api, self.admin, self.mcp_token, self.trader = api, admin, mcp_token, trader
        self.transcript = transcript
        self.results: List[Tuple[str, bool, str]] = []
        self.log: List[str] = []

    def check(self, step: str, ok: bool, detail: str = "") -> bool:
        self.results.append((step, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {step}" + (f"  ({detail})" if detail else ""), flush=True)
        return ok

    def params(self, allow_trading: bool) -> StdioServerParameters:
        env = {k: v for k, v in os.environ.items() if k not in ("COPYCAT_AGENT_KEY", "COPYCAT_API_TOKEN")}
        env.update({"COPYCAT_API_URL": self.api, "COPYCAT_MCP_TOKEN": self.mcp_token,
                    "COPYCAT_SKIP_DOTENV": "1"})
        if allow_trading:
            env["COPYCAT_MCP_ALLOW_TRADING"] = "1"
        else:
            env.pop("COPYCAT_MCP_ALLOW_TRADING", None)
        return StdioServerParameters(command=str(RUN_SH), args=[], env=env)

    async def call(self, s: ClientSession, name: str, args: Dict[str, Any]) -> Tuple[bool, Any, str]:
        r = await s.call_tool(name, args)
        text = "\n".join(getattr(b, "text", "") for b in r.content)
        try:
            data = json.loads(text)                   # the tool's dict, as the model reads it
        except ValueError:
            data = getattr(r, "structured_content", None)
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
        self.log.append(f"## {name}({json.dumps(args)})\nerror={bool(r.is_error if hasattr(r, 'is_error') else r.isError)}\n"
                        f"{text[:1500]}\n")
        err = bool(getattr(r, "is_error", None) if hasattr(r, "is_error") else r.isError)
        return (not err), data, text

    def pending(self) -> List[Dict[str, Any]]:
        r = httpx.get(f"{self.api}/api/mcp/plans/pending", headers={"Authorization": f"Bearer {self.admin}"},
                      timeout=10)
        r.raise_for_status()
        return r.json()

    async def run(self) -> int:
        # Step 1 (DEMO "Install"): without the flag, research tools only.
        async with stdio_client(self.params(False)) as (rd, wr), ClientSession(rd, wr) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            self.check("1. without COPYCAT_MCP_ALLOW_TRADING: research tools only, no execute",
                       names == READ_TOOLS, f"{len(names)} tools")
            prompts = {p.name for p in (await s.list_prompts()).prompts}
            self.check("1. prompts copy_trader and write_thesis are offered",
                       {"copy_trader", "write_thesis"} <= prompts)

        async with stdio_client(self.params(True)) as (rd, wr), ClientSession(rd, wr) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            self.check("1. with the flag: execute_copy_plan appears, nothing else that moves money",
                       names == READ_TOOLS | {"execute_copy_plan"})

            # Step 2 (DEMO "Find a trader"): the Scout board.
            ok, data, _ = await self.call(s, "scout_list", {"limit": 30, "sort": "fit"})
            rows = (data or {}).get("rows") or []
            self.check("2. scout_list returns ranked traders", ok and len(rows) > 0, f"{len(rows)} rows")
            if self.trader == "auto":
                # The demo needs a trader worth explaining: real trades to fingerprint and
                # open positions to copy. Take the best Copy Fit row that has both.
                for row in rows:
                    if int(((row.get("trades_30d") or {}).get("trips")) or 0) < 5:
                        continue
                    ok_p, prof, _ = await self.call(s, "trader_profile", {"address": row["address"], "wait_s": 60})
                    if ok_p and isinstance(prof, dict) and prof.get("positions"):
                        self.trader = row["address"]
                        break
                self.check("2. picked a trader with 5+ trades and open positions", self.trader != "auto",
                           self.trader)
                (self.transcript.parent / "trader.txt").write_text(self.trader)

            # Step 3 (DEMO "Understand the strategy").
            ok, prof, _ = await self.call(s, "trader_profile", {"address": self.trader, "wait_s": 90})
            self.check("3. trader_profile returns his file", ok and isinstance(prof, dict)
                       and prof.get("status") != "building", str((prof or {}).get("status") or "ready"))
            ok, fp, _ = await self.call(s, "trader_fingerprint", {"address": self.trader, "wait_s": 120})
            self.check("3. trader_fingerprint returns a deterministic summary from real trades",
                       ok and isinstance(fp, dict) and bool(fp.get("summary"))
                       and int(fp.get("trips_analyzed") or 0) > 0,
                       f"trips_analyzed={(fp or {}).get('trips_analyzed')}")

            # Step 4 (DEMO "Make a plan").
            ok, cp, text = await self.call(s, "copy_plan", {"address": self.trader, "amount_usd": 50,
                                                            "leverage": 3, "entry_deviation_pct": 50})
            plan = (cp or {}).get("plan") or {}
            pid = plan.get("plan_id")
            self.check("4. copy_plan builds a plan with an id and a table to show",
                       ok and bool(pid) and "|" in str((cp or {}).get("present")), str(pid))
            pv = plan.get("preview") or {}
            self.check("4. the plan sizes at least one of his positions",
                       len(pv.get("slices") or []) > 0, f"{len(pv.get('slices') or [])} positions, "
                       f"{pv.get('copied')} copied, ${pv.get('planned_margin_usd', 0):,.2f} margin")
            pend = self.pending()
            mine = next((p for p in pend if p["plan_id"] == pid), None)
            code = (mine or {}).get("confirm_code") or ""
            self.check("4. the confirm code is in copycat (Portfolio > Pending MCP plans)",
                       len(code) == 6, "code read via GET /api/mcp/plans/pending")
            self.check("4. Claude never sees the code (not anywhere in copy_plan's output)",
                       bool(code) and code.upper() not in text.upper())

            # Step 5 (DEMO "Approve"): wrong code refused, right code executes, replay refused.
            ok, _, t = await self.call(s, "execute_copy_plan", {"plan_id": pid, "confirm_code": "ZZZZZZ"})
            self.check("5. a guessed code is refused", not ok, t.splitlines()[0][:80] if t else "")
            ok, res, t = await self.call(s, "execute_copy_plan", {"plan_id": pid, "confirm_code": code})
            self.check("5. the code from copycat executes the plan",
                       ok and bool((res or {}).get("executed")), t[:80].replace("\n", " "))
            ok, _, t = await self.call(s, "execute_copy_plan", {"plan_id": pid, "confirm_code": code})
            self.check("5. a plan runs once: the same code again is refused", not ok)

            # Step 6 (DEMO "Check it"): the wallet is in the book, trading untouched.
            ok, st, _ = await self.call(s, "copycat_settings", {})
            leaders = [a.lower() for a in (st or {}).get("leaders") or []]
            self.check("6. the trader is now in your book", self.trader.lower() in leaders)
            self.check("6. execute never turned trading on",
                       (st or {}).get("enabled") is False and (st or {}).get("dry_run") is True)
            ok, w, _ = await self.call(s, "my_wallets", {})
            self.check("6. my_wallets lists the new copy", ok and self.trader.lower() in json.dumps(w).lower())

        # Step 7 (DEMO "What Claude cannot do"): the scoped token is refused off-scope.
        for method, path in (("PUT", "/api/settings"), ("POST", "/api/engine/halt"),
                             ("GET", "/api/mcp/plans/pending"), ("GET", "/api/accounts")):
            r = httpx.request(method, f"{self.api}{path}", headers={"Authorization": f"Bearer {self.mcp_token}"},
                              json={} if method != "GET" else None, timeout=10)
            self.check(f"7. MCP token cannot {method} {path}", r.status_code == 403, str(r.status_code))

        self.transcript.write_text("\n".join(self.log))
        fails = sum(1 for _, ok, _ in self.results if not ok)
        print(f"\n{len(self.results) - fails}/{len(self.results)} checks passed. Transcript: {self.transcript}")
        return fails


def main() -> None:
    api, admin, mtok, trader, transcript = sys.argv[1:6]
    sys.exit(asyncio.run(Demo(api.rstrip("/"), admin, mtok, trader, Path(transcript)).run()))


if __name__ == "__main__":
    main()
