"""The `write_thesis` prompt and the deterministic check for its output.

The thesis is latent work (Claude reads the evidence and writes prose). The
section list is deterministic: `missing_sections()` checks a draft against
it, `save_thesis` reports the result, and the gate tests pin both the prompt
text and the checker to the same `THESIS_SECTIONS` tuple.
"""
from __future__ import annotations

import re
from typing import List

# Order matters: the prompt lists them in this order and asks for `## <name>` headings.
THESIS_SECTIONS = (
    "Edge in one sentence",
    "How they enter",
    "Sizing & risk",
    "Exits",
    "When they trade",
    "What a copier should know",
    "What you can learn and practice",
    "Confidence & caveats",
)

THESIS_MAX_CHARS = 20_000   # contracts.models.Thesis.markdown max_length (a gate test pins it)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("&", " and ")).strip()


def missing_sections(markdown: str) -> List[str]:
    """Required sections with no matching markdown heading (any level).
    A heading matches if it starts with the section name, ignoring case,
    punctuation and `&` vs `and`; e.g. "## How they enter (evidence)" counts."""
    headings = [_norm(m.group(1)) for m in re.finditer(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", markdown, re.M)]
    return [s for s in THESIS_SECTIONS if not any(h.startswith(_norm(s)) for h in headings)]


def write_thesis_prompt(address: str) -> str:
    sections = "\n".join(f"   {i}. `## {name}`" for i, name in enumerate(THESIS_SECTIONS, 1))
    return f"""You are writing a strategy thesis for the Hyperliquid trader {address}, using the copycat MCP tools.
The reader is a copycat user deciding whether to copy this trader and wanting to learn from them.

## 1. Gather evidence (tools, in this order)
1. `trader_fingerprint(address)`: the deterministic TA fingerprint: style, hold times, entry habits
   (trend_aligned / breakout / pullback shares, RSI at entry), sizing (adds, scaling, leverage),
   outcomes (win rate, payoff ratio, loser vs winner hold), timing histograms, tags, its own
   templated summary, `examples` and `caveats`. Note `trips_analyzed`, `window_days` and `as_of_ms`.
2. `trader_profile(address)`: account size, open positions, risk stats, per-window trade stats, coins.
3. `trader_trades(address)`: up to 8 fingerprint examples WITH entry context, plus recent round trips.
4. Pick 3-5 key entries: the fingerprint's examples plus anything that contradicts the pattern
   (largest win, largest loss, a typical entry). For each, call `market_candles(coin, "1h",
   start_ms=opened_ms - 48h, end_ms=closed_ms + 6h)` (use "15m" for holds under ~6h) and look at
   what price did before entry, at entry and through the exit.
5. `list_theses(address)`: read earlier theses so you refine instead of repeating.
Use `trader_fills(address)` only if a round trip needs fill-level detail.

## 2. Write the thesis in markdown, with exactly these sections as `##` headings, in this order:
{sections}

What each section must contain:
- Edge in one sentence: the single most defensible claim about where their returns come from.
- How they enter: the setup (trend, breakout, pullback, mean reversion, news-like spikes), with evidence:
  fingerprint percentages AND the specific trades you checked on candles.
- Sizing & risk: leverage (avg and max), scaling in/out, worst trip as % of equity, concentration.
- Exits: how winners and losers end, loser hold vs winner hold, payoff ratio.
- When they trade: hours (UTC) and weekdays from the histograms; activity level.
- What a copier should know: fit for small accounts (HL $10 minimum order, fixed-margin copies),
  leverage and liquidation risk at the copier's own leverage, latency sensitivity (short holds and
  breakout entries degrade most when copied seconds late), concentration in one coin.
- What you can learn and practice: concrete habits a trader could study or paper-trade.
- Confidence & caveats: sample size (trips_analyzed, window_days), missing candles, regime dependence,
  the fingerprint's own caveats, and what would change your mind.

## 3. Rules
- Cite trade examples by coin, side and UTC date (e.g. "BTC long, 2026-09-14"). Convert timestamps with
  a tool or code, never by guessing.
- Quote numbers from the tools; do not invent or round them into new claims.
- Never claim certainty from small samples. Under ~30 round trips, say so in the first section and
  hedge every pattern claim. Past behavior does not predict future results.
- No financial advice framing: describe and explain, never tell the reader to buy, sell, copy or size up.
- Keep it under 20,000 characters.

## 4. Save
Call `save_thesis(address="{address}", title=<short title naming the style>, markdown=<the thesis>,
author=<your model name> + " via copycat MCP")`. If it reports missing sections, fix the draft and
save again. Then show the user the title and the "Edge in one sentence" line.
"""
