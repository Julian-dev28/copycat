---
description: Research a Hyperliquid trader with the copycat MCP tools and save a strategy thesis
argument-hint: <0x trader address>
---

Use the `copycat` MCP server's `write_thesis` prompt for the trader `$ARGUMENTS` and follow it exactly:

1. Gather evidence with `trader_fingerprint`, `trader_profile`, `trader_trades`, `market_candles` around 3 to 5 key entries, and `list_theses`.
2. Write the thesis with the eight required `##` sections, in order: Edge in one sentence, How they enter, Sizing & risk, Exits, When they trade, What a copier should know, What you can learn and practice, Confidence & caveats.
3. Cite trades by coin, side and UTC date. Quote numbers from the tools. Hedge every claim when the sample is small. No financial advice.
4. Save it with `save_thesis` (author: your model name + " via copycat MCP"), fix any missing sections it reports, then show me the title and the one-sentence edge.

If a tool says the api is down or the token is wrong, tell me how to fix it (start copycat with `make dev`, or set `COPYCAT_API_TOKEN`) instead of guessing.
