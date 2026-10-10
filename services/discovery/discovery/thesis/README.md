# discovery.thesis

Deterministic strategy fingerprint and TA thesis. Given a trader's fills and
1h candles, it describes what the trader does to make money, so users can
learn from them. **No AI anywhere in this package.** Same input, same
fingerprint, same text, byte for byte. The `claude_code` thesis (written by
the user's Claude Code through the MCP server) is only stored here, never
generated.

## Public surface (`discovery.thesis.public`)

| function | returns |
|---|---|
| `fingerprint(address, window_days=30, venue=None, *, refresh=False)` | `StrategyFingerprint`, reused from the store within the TTL |
| `ta_thesis(address, fingerprint=None)` | `Thesis(source="ta")`. Pass a fingerprint you already have to skip the recompute; otherwise the stored one is reused within its TTL. Saved as the latest `ta` thesis. |
| `save_thesis(thesis)` | stores a thesis, replacing the previous one of the same source |
| `get_theses(address)` | `List[Thesis]`, latest per source, newest first |
| `ThesisError` | raised when the fills read fails (a failed read never looks like a flat trader) |

`discovery.candles_public.candles(coin, interval, start_ms, end_ms)` returns
`[{t_ms, o, h, l, c, v}]` through the same candle cache, clamped to HL's
newest 5000 bars. It is for the api's candles route.

CLI: `python -m discovery.thesis 0xADDR [--days 30] [--refresh] [--markdown]`.

## Data flow

1. **Fills**: `fills_cache.sync_fills` on `data/discovery.db` (incremental,
   tail skipped when fetched within `COPYCAT_DISCOVERY_FRESH_S`, default 900s).
2. **Trips**: `positions.reconstruct` on perp fills (spot `@N`, `PURR/USDC`
   and outcome `#N` coins are dropped). Flat to flat per coin; a flip is a
   close then an open. A trip already open at the first fill is dropped, one
   still open at the last fill is counted only in a caveat.
3. **Candles**: 1h bars through `candles_cache.ensure_cached`, per coin, from
   `WARMUP_BARS + 2` hours before the first entry to the last entry. HL serves
   ~5000 bars per interval, so 1h reaches ~208 days; a 30-day window fits.
4. **Account value**: HL `portfolio`, `month` and `allTime` accountValueHistory
   merged (month wins on equal timestamps). Fallback: today's
   `equity_perp_usd + spot_usdc` as one point, with a caveat.
5. `fingerprint.build_fingerprint(...)`: pure, no I/O, no clock.
6. `template.render_summary` / `render_markdown`: string assembly.

HL reads use `COPYCAT_HL_PRIORITY=background` (`public.use_background_priority`).

## Storage

Two tables in `data/discovery.db` (same WAL file as the caches it reads, so
one connection serves both; `$COPYCAT_DATA_DIR` moves it):

- `thesis_fingerprints (address, window_days) -> as_of_ms, payload_json`
- `thesis_texts (address, source) -> created_ms, payload_json`, one row per source

TTL: a stored fingerprint younger than `COPYCAT_THESIS_TTL_S` (default 3600s)
is returned as is. Older rows stay on disk and are recomputed on the next read.

## Entry context (`indicators.py`), per trip at its first fill

Look-ahead rule: only 1h bars that **closed** at or before the entry
(`bar start + 1h <= entry`) are used. Each entry uses its own slice of the
last 200 closed bars, so one trip's context never depends on other trips.
If the last closed bar ended more than 3h before the entry, the entry has
no context (all fields None, `hour_utc` still set). `px` is the trip's
first fill price.

| field | formula |
|---|---|
| EMA50 | seeded with the SMA of the first 50 closes, then `c*k + prev*(1-k)`, `k = 2/51`. Needs 55 bars. |
| `trend_aligned` | slope = `EMA50[last] - EMA50[last-5]`; long: slope > 0, short: slope < 0 (0 is not aligned) |
| `breakout` | long: `px >= high20 * (1 - 0.005)`; short: `px <= low20 * (1 + 0.005)`. high20/low20 over the last 20 closed bars' highs/lows. Needs 20 bars. |
| `pullback` | long: `px <= high20 * 0.98` and `px > EMA50`; short: `px >= low20 * 1.02` and `px < EMA50` |
| `rsi_14` | Wilder RSI(14) of the closes: SMA seed of the first 14 gains/losses, then `(prev*13 + x)/14`. 100 with no losses, 50 when flat. Needs 15 closes. |
| `move_24h_pct` | `(px / close_j - 1) * 100`, `j` = the last bar closed at or before entry - 24h (same 3h staleness rule) |
| `hour_utc` | `(entry_ms // 3600000) % 24` |

## Trips (`trips.py`)

- `adds`: add events, where fills within 60s of the previous entry-side fill
  are the same action (a TWAP or a sweep of resting orders is one add).
- `exits`: reduce + close actions, same 60s merge. `scales out` = exits >= 2.
- `net_pnl_usd = sum(closed_pnl) - sum(fee)` over the trip's fills.
- `max_notional_usd = max(|position| * fill px)` over the trip's fills.
- `return_pct = net_pnl_usd / max_notional_usd * 100`.

## Fingerprint fields (`fingerprint.py`)

Percentages are 0..100. Candle-based percentages use only trips with
context as the denominator; None when no trip has context.

| field | formula |
|---|---|
| `trips_analyzed` | closed trips opened in `[now - window, now]` |
| `style` | `scout.metrics.classify_style(opens/day, median hold, trips)` (algo > 100 opens/day; scalp < 15m, intraday < 24h, swing < 7d, else position; None under 3 trips). Imported so the board and fingerprint agree. opens/day = (closed + still open trips) / window_days. |
| `median_hold_h` / `p90_hold_h` | median; nearest-rank p90 = `sorted[ceil(0.9 n) - 1]` |
| `long_pct` | long trips / trips |
| `trend_aligned_pct`, `breakout_pct`, `pullback_pct` | share of trips with that context True |
| `avg_rsi_long_entry` / `short` | mean entry RSI over long / short trips with RSI |
| `avg_adds_per_trip` | mean adds |
| `scales_in_pct` / `scales_out_pct` | trips with adds >= 1 / exits >= 2 |
| `avg_leverage` / `max_leverage` | per trip **effective** leverage = `max_notional / account value at open` (last positive accountValueHistory point at or before the open, else the first after). Not the exchange leverage setting: fills do not carry it. |
| `win_rate_pct` | trips with net > 0 / trips |
| `avg_win_usd` / `avg_loss_usd` | mean net of trips with net > 0 / net < 0 (break-even trips are neither) |
| `payoff_ratio` | `avg_win / abs(avg_loss)` |
| `loser_hold_vs_winner` | median loser hold / median winner hold |
| `worst_trip_pct_of_equity` | min over trips of `net / account value at open * 100` (negative = loss) |
| `pnl_from_top_coin_pct` | best coin's realized PnL / sum of positive coins' realized PnL * 100. Realized PnL per coin = `sum(closed_pnl - fee)` over the window's fills. None when no coin made money. |
| `hour_hist_utc` / `weekday_hist` | entry counts per UTC hour (24) and weekday (7, Monday first) |
| `entries_by_dow_hour` | 7 x 24 entry counts, `[weekday][hour]`, UTC, Monday first (rows sum to `weekday_hist`, columns to `hour_hist_utc`); empty on fingerprints cached before it existed |
| `top_coins` | top 5 by window fill volume `sum(px*sz)`, plus the most profitable coin if it is not in them |
| session window | best 6h UTC window (wraps midnight, earliest start wins ties); share = its entries / all entries |

## Tags (`config.TAG_RULES`, evaluated in this order)

No tags under 5 trips. Candle tags also need >= 5 trips with context. A None
metric never matches.

| tag | rule |
|---|---|
| trend follower | `trend_aligned_pct >= 65` |
| counter-trend | `trend_aligned_pct <= 35` |
| dip buyer | `pullback_pct >= 40` |
| breakout buyer | `breakout_pct >= 40` |
| scales in | `scales_in_pct >= 50` |
| scales out | `scales_out_pct >= 50` |
| runs winners | `payoff_ratio >= 2` |
| cuts losers fast | `loser_hold_vs_winner < 0.5` |
| holds losers | `loser_hold_vs_winner >= 2` |
| high win rate | `win_rate_pct >= 65` |
| high leverage | `avg_leverage >= 10` |
| concentrated | `pnl_from_top_coin_pct >= 60` |
| session trader | best 6h UTC window share `>= 50` |
| long biased | `long_pct >= 75` |
| short biased | `long_pct <= 25` |

## Examples (up to 8, fixed rules, a trip is never shown twice)

Rules, in order, until 8 are chosen: largest win (max net); largest loss
(min net, if any loser); for each tag in tag order that has a trip predicate,
the **typical** trip matching it (trend follower: trend-aligned;
counter-trend: not aligned; dip buyer: pullback; breakout buyer: breakout;
scales in: adds >= 1; scales out: exits >= 2; runs winners: winners; cuts
losers fast and holds losers: losers; session trader: entry in the session
window); the most typical trip overall; highest leverage; longest hold; most
adds; best return on notional; worst return on notional; then the most
recent trips.

Typical = closest to the candidate set's median `return_pct`, then median
hold, then earliest open, then coin name. All ties break on open time, so
the selection is deterministic.

## Caveats

Emitted when they apply: no closed trips; under 5 trips (no tags); under 20
trips ("a sketch, not a pattern"); trips with no usable 1h candles (count and
coins); a candle read failure; positions still open; no account value
history; the effective-leverage note; the HL 10,000-fill cap reached (>= 9000
fills and the oldest more than a day after the window start); a window longer
than 1h candles reach (~208 days); over 100 opens per day.

## Summary template (`template.render_summary`)

Sentences in this order, each emitted only when the numbers it quotes exist,
capped at 8: headline (`[Trend-following|Counter-trend] <style> trader on
<coins>`, coins = up to 3 top coins with >= 10% of listed volume); dominant
entry (pullback vs breakout, direction word when long_pct >= 75 or <= 25);
trend share + average RSI; win rate + long share; payoff ("Lets winners run"
when tagged, "edge comes from the hit rate" when payoff < 1); holds and the
loser/winner ratio ("closed almost at once" under 0.05); adds and scale-outs;
effective leverage and worst trip; session window (when tagged); profit
concentration (when >= 50%). Zero trips gives one sentence. No em or en
dashes (gate-tested).

The `ta` thesis markdown has: How they trade, Entries, Sizing & risk, When,
What to learn (one fixed lesson line per tag), Evidence (examples table),
Caveats.

## Tests

- Gate (no network, < 1s): `test_thesis_indicators.py`, `test_thesis_metrics.py`,
  `test_thesis_template.py`, `test_thesis_store.py` (fixtures in
  `test_thesis_fixtures.py`).
- Live eval: `.venv/bin/python -m pytest services/discovery/tests/test_thesis_live.py -m live -s`
  fingerprints 3 real leaders and checks: trips > 0, 4 to 8 sentences, no
  dashes, known tags only, 1..8 unique examples, text regenerates identically,
  >= 2 of 3 leaders have candle context.
