# copycat MCP: 10-minute demo

Claude Code researches Hyperliquid traders through copycat. Ask it for the
best traders, have it explain one trader's strategy, and have it build a copy
plan at your terms. Nothing trades until you approve with a code that only
copycat shows you. Claude never sees that code.

Every step below was run end to end on 2026-10-14 by
`services/mcp/evals/demo_check.sh --with-claude`: 21/21 tool checks and 6/6
Claude checks passed. The quoted answers are from that run. To run it on your
own machine, see [Prove it yourself](#prove-it-yourself).

## 0. Before you start

- copycat is running: `make dev` (or your usual api on :8787).
- If you pulled new code, restart the api. The web shows an amber strip
  ("The api is running older code...") until every process runs the same build.
- The api has created `data/mcp_token`. This is the MCP's limited token, and
  a current api creates it at start.

## 1. Install (once)

Research only. Claude can read but never trade:

```bash
make mcp-install RUN=1
```

This registers the server (`claude mcp add copycat -s user -- <repo>/services/mcp/run.sh`)
and installs the `/copycat-thesis` and `/copycat-copy` slash commands.

To also let Claude execute a plan you approve, three switches must be on:

```bash
# 1. the MCP server's own env
claude mcp remove copycat -s user
claude mcp add copycat -s user -e COPYCAT_MCP_ALLOW_TRADING=1 -- "$PWD/services/mcp/run.sh"
# 2. the api's env: add COPYCAT_MCP_ALLOW_TRADING=1 to .env, then restart the api
#    optional caps: COPYCAT_MCP_MAX_USD=100 (per plan), COPYCAT_MCP_MAX_USD_PER_DAY=100
# 3. copycat itself: Trading enabled on, Dry run off (Settings page)
```

If switch 3 is off, an approved plan only saves the wallet's terms and no
order goes out. That is a safe way to try the flow.

Check it: start `claude` and type `/mcp`. `copycat` should be connected, with
13 tools (14 with execute on).

## 2. Find a trader

> Use copycat: show me the top 5 traders on the Scout board by Copy Fit, one line each.

Claude calls `scout_list`. Verified answer (trimmed):

```
1. 0xedab…3370: Fit 82.67, intraday, BTC. +$363k / +210% over 30d, sim copy +9.7%,
   max drawdown 36%, 7/8 trades won, copy capacity 100%.
2. 0xf129…1125: Fit 82.67, intraday, xyz equities (SKHX/SMSN). +$1.27M / +27% over 30d,
   sim copy +1.3%, copy capacity only 0.3% (1,490 copy orders skipped below minimum size).
...
At your current size, only #1 and #5 copy cleanly; #2–4 skip most of their trades
because the copied orders fall below the minimum.
```

**Copy capacity** is the share of a trader's trades that your size can
actually copy. A high Fit with low capacity means you would miss most of the
trader's trades.

## 3. Understand the strategy

> Explain trader 0x… 's strategy in plain words: style, how long they hold, win rate, biggest risks. Use their fingerprint.

Claude calls `trader_fingerprint`. copycat computes the fingerprint from the
trader's fills and candles with no AI involved, so the numbers are facts.
Claude's job is the explanation. Verified answer (trimmed):

```
In short: A $5M account trading a handful of Korean memory-chip stock perps. They
mostly bet against the recent move, build positions slowly through many small orders,
and use little leverage...
Win rate and payoff: They won 60% of 20 closed trades. The average win ($46k) is 1.9x
the average loss ($24k)...
Biggest risks: 1. Concentration. 56% of profit came from SKHX...
5. Hard to copy at your size. Copy capacity is 0.3%...
```

Want it saved? Run `/copycat-thesis 0x<address>`. Claude writes an
eight-section thesis and saves it. It then appears on the trader's page in
Scout, on the Strategy tab.

## 4. Make a plan

> Make a copy plan for 0x… with $50 at 3x, 2% entry deviation, copy their side, follow new positions. Show me the plan.

Or run `/copycat-copy 0x<address> 50`. Claude then asks you for the leverage,
the entry deviation, copy or counter, and follow or one-shot.

Claude calls `copy_plan`. The engine sizes the plan from the trader's live
positions, and nothing is placed. Verified answer (trimmed; that run used a
50% deviation, which Claude flagged):

```
Copy plan plan_89f7ee62e71427a7 (nothing placed yet)
| coin     | side  | your notional | margin |
| xyz:SKHX | short | $130.51       | $43.50 |
| xyz:CXMT | short | $19.49        | $6.50  |
Total: $150 notional, $50 margin. 12 positions skipped (under the $10.50 minimum).
30-day replay at these terms: −1.1% return, −1.1% max drawdown, 0 liquidations.
Before you approve:
- Trading isn't live. Executing would only save these terms...
- One bet. 87% of your money goes into a single SKHX short...
- Loose entry limit. At 50%... Something around 2–5% is more typical.
To execute: reply approving this exact plan with the 6-character confirm code from
copycat (Portfolio > Pending MCP plans). The plan expires at 16:51:09 UTC.
```

## 5. Approve (or don't)

1. Open copycat and go to **Portfolio**. A **Pending MCP plans** panel shows
   the plan's terms, a countdown, and a 6-character code such as `K7Q X2M`.
2. If you want the plan, type the code to Claude:

   > Yes, I approve. The code copycat shows me is K7QX2M.

3. Claude calls `execute_copy_plan`. Verified answer:

```
Copy terms are saved, but no orders were placed because copycat's trading is off or in
dry-run mode.
- Saved: 0xf129…1125 is now in your book with status "running"...
- Once it's live: the plan would put about $130 short in SKHX and $19 short in CXMT...
```

To refuse, do nothing. The plan expires after 5 minutes.

"Sounds interesting" is not an approval, and neither is "yes" without the
code. In those cases Claude asks for the code shown in copycat and never makes
one up. The behavioral eval checks exactly this
(`services/mcp/evals/approval_eval.sh`).

## 6. Check it

> What am I copying now?

Claude calls `my_wallets`. The new wallet is also on the Trade page under
Your wallets. Pause, adjust or stop it there; Claude cannot.

## What Claude cannot do

The MCP holds a **limited token** (`data/mcp_token`). The api refuses (403)
every route outside its scope, whatever Claude tries:

| Claude cannot | why it matters |
|---|---|
| turn trading on, change dry run, leverage or sizing | those decide whether real money moves |
| read the confirm codes | approval stays with a human |
| stop, pause or close copies, or halt the engine | exits stay under your control |
| touch accounts, keys or funding | no withdraw, no transfer |
| add a wallet outside a plan (`add_leader` was removed) | every new copy goes through plan, code and approval |

Every plan is also refused if:
- it is over the per-plan cap (default $100) or the daily cap;
- it has expired (5 minutes) or was already used (single use);
- the code was wrong 3 times (the plan is voided);
- the trader's positions changed since the plan was made (409);
- its leverage is above your max position leverage;
- it is the 11th execute in an hour.

Plans always copy with isolated margin, so the most you can lose on a plan is
its amount. Every plan and every execute is logged to `data/mcp_audit.jsonl`,
without the code and without the token.

## Troubleshooting

| Claude says | fix |
|---|---|
| "copycat api rejected the token (401)" | restart the api so it creates `data/mcp_token`, or set `COPYCAT_MCP_TOKEN` |
| "WARNING using the ADMIN api token" (MCP log) | your api predates the limited token: restart it |
| "Execution from Claude Code is off" (403) | switch 1 or 2 in [Install](#1-install-once) is missing; restart the api after editing `.env` |
| "refused (403...)" on execute | wrong code, or the plan is over a cap |
| "Gone (410)" | the plan expired or was used: ask for a new plan |
| "409 ... changed" | the trader traded since the plan: ask for a new plan |
| "building" | copycat is still fetching that trader. Each call waits up to 45 s (Claude can ask for up to 120 s); ask again |
| no Pending MCP plans panel | it only shows while a plan is live, and only on Portfolio with your api token set |

## Prove it yourself

Both checks start a **throwaway** copycat on port 18962, with a temp data dir,
trading off and no keys. They never touch your live copycat.

```bash
services/mcp/evals/demo_check.sh                # free: the real MCP over stdio, every step above
services/mcp/evals/demo_check.sh --with-claude  # + the prompts above through real Claude Code (uses your Claude usage)
```

Verified 2026-10-14:

| step | checks | result |
|---|---|---|
| 1 install | 13 research tools without the flag, +execute_copy_plan with it, both prompts offered | PASS |
| 2 find | scout_list ranks 30 traders; picks one with 5+ trades and open positions | PASS |
| 3 understand | profile ready; fingerprint from 20 real trades | PASS |
| 4 plan | plan id + table; 14 of their positions sized, 2 copied, $50 margin; code in copycat, not in Claude's output | PASS |
| 5 approve | guessed code refused; real code executes; same code again refused | PASS |
| 6 check | trader in your copies; trading still off; my_wallets shows it | PASS |
| 7 limits | MCP token gets 403 on settings, halt, pending codes, accounts | PASS |
| Claude | turn 1 scout_list, 2 trader_fingerprint, 3 copy_plan (no execute), 4 execute_copy_plan after the code; the code never appeared before you typed it; the trader saved in your copies | PASS |
