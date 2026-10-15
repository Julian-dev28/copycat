# discovery

Ranks Hyperliquid leaderboard wallets by what COPYING them would have
earned you at your own settings and equity, not by their own PnL. Read-only
against Hyperliquid (it never signs anything). No AI.

Public surface: `discovery.public` (`start_run`, `get_run`, `latest`,
`create_run`, `run_worker`). Everything else is internal.

## CLI

```bash
export PYTHONPATH=.:services/hl:services/engine:services/discovery

# a run: progress with ETA, then the ranked table
.venv/bin/python -m discovery --equity 100 --top 20 --days 30 [--include-hft]

# execute an already-created run (what start_run(mode="subprocess") spawns;
# the api can launch runs out of process this way)
.venv/bin/python -m discovery worker --run-id <run_id>

# one wallet: reconstructed positions vs his live account + copy-sim trace
.venv/bin/python -m discovery trace --wallet 0x... --equity 100 --days 30
```

Tests: `.venv/bin/python -m pytest services/discovery/tests` (gate, no
network, <1s). Live eval: `-m live services/discovery/tests/test_live.py`.

## Pipeline

1. **Leaderboard** (`leaderboard.py`): stats-data GET (~47k rows, ~10-15s),
   slimmed to positive-PnL rows and cached in `kv` for
   `COPYCAT_DISCOVERY_LEADERBOARD_TTL_S` (900s). Filters: account value,
   30d volume, 30d and all-time PnL > 0. Ranked by 30d PnL, top_n kept.
   Vaults kept, flagged `vault`.
2. **Per wallet, 4 at a time** (`runner.py`, thread pool; HL budget is the
   bottleneck, the pool hides round-trip latency):
   1. **Fills** (`fills_cache.py`): coverage-tracked incremental cache.
      Fetches only `[window_start, first_ms)` and `(last_ms, now]`. A failed
      read raises and moves nothing (it used to advance the cursor and make
      the wallet look flat forever). Tail skipped when fetched less than
      `COPYCAT_DISCOVERY_FRESH_S` (900s) ago.
   2. **Perp filter** (`positions.split_perp`): drops spot (`@151`,
      `PURR/USDC`) and outcome (`#12100`) fills, flag `non_perp_ignored`.
   3. **Poll coalescing** (`positions.coalesce_by_poll`): fills of one coin
      inside one `poll_interval_s` become one net delta, because that is all
      the engine sees. An open+close inside one poll is invisible to it.
   4. **Reconstruct** (`positions.reconstruct`): open/add/reduce/close from
      `start_position` + signed size; a flip is close + open.
   5. **HFT gate**: opens/day > 100 is flagged `hft` and not simulated
      (`hft_not_simulated`, uncopyable at 5s polling) unless `include_hft`.
   6. **Candles** (`candles_cache.py`): only for coins and periods where they
      held a position that OPENED in the window (`positions.trip_spans`).
   7. **Copy-sim** (`sim.py`) and **score** (`scoring.py`).
3. **Persist**: `results` rows as each wallet finishes; `runs.scored`,
   `runs.candidates`, `runs.heartbeat_ms` drive progress and ETA.

All state lives in `$COPYCAT_DATA_DIR/discovery.db` (WAL), so any process
can read a run another process executes. A `running` row whose heartbeat is
older than `COPYCAT_DISCOVERY_STALE_RUN_S` (600s) is marked failed instead of
blocking new runs forever.

HL budget: every run switches the process to hl's `background` priority
(`hl.rate_limit.set_priority("background")`), so the shared per-IP bucket
keeps a reserve for the live engine.

## Candle window: what HL serves shapes the sim

HL's `candleSnapshot` only returns the most recent ~5000 bars of each
interval (measured 2026-10-03): 1m reaches back **3.5 days**, 5m 17.4 days,
15m 52 days, 1h ~208 days. Older bars do not exist at HL. So the price
series is tiered by age (`candles_cache.tier_bounds`, 4900-bar margin):

| age of the bar | resolution | what it means for the sim |
|---|---|---|
| last ~3.4 days | 1m | entry at the next 1m open; liquidation checked per minute |
| 3.4 to ~51 days | 15m | entry at their fill price + 5 bps; liquidation checked per 15m bar |
| older | 1h | same, per hour (only for windows > 51 days) |

A bar's high/low contains every wick inside it, so a coarse bar never MISSES
a liquidating wick; what coarse bars lose is ordering at the edges (see
biases). Coverage of what HL actually answered is stored per
(coin, interval), so missing bars (old data, no-trade minutes on thin HIP-3
markets) are not re-requested every run. The newest bar is still forming and
is refreshed on the next run.

## Sim model

Per wallet, starting at `sim_equity_usd`, copying ONLY this wallet
(`n_leaders = 1`), at the run's `Settings` (with his `leader_overrides`):

- Sizing, leverage, min-order bump and liquidation distance all come from
  `engine.sizing` (imported, not re-implemented). Maintenance margin is
  `1 / (2 * coin_max_leverage)`. Leverage is fixed per copy at open.
- Entry sizing follows `engine.core._execute_entry`: raw notional from
  `engine.sizing` (`open_notional` / `add_notional`, all four sizing modes
  incl. `allocation`, whose `his_gross_ntl_after` comes from their in-window
  book), trimmed to margin room (free margin x lev x 0.95), trimmed to the
  allocation cap (allocation mode), bumped, skipped if still under $10.50.
  Opens also skip on unknown max leverage, `max_open_copies`, or worse than
  `max_worse_entry_pct` vs their fill. Isolated free margin is cash minus
  posted margin: an open copy's unrealized gain cannot back new orders.
- **Fixed modes never grow a copy past its fixed size**: in `fixed_margin`
  / `fixed_notional`, total copy margin <= max(fixed margin, margin posted
  at open) x 1.02. Adds beyond that are skipped (`add_capped:<coin>`); after
  a reduce, adds may refill up to it. See "Fixed-size cap" below.
- Add: at the copy's leverage; average entry and liquidation price move.
- Reduce/close: proportional / full; exits are never gated.
- Mark-to-market: bar by bar across coins in end-time order; max drawdown
  is on the marked equity. Liquidation: a wick through the liquidation
  price loses exactly that copy's posted margin. Unrealized loss of a copy
  is floored at its margin, so a price gap in the data can never cost more.
- Fees: 0.045% taker on every leg.
- Contract v8, from the effective settings: `trade_direction` counter opens
  the opposite of their side at the same size; fill price, worse-entry check,
  liquidation price and PnL are all on our inverted side (a copy that wins
  is a counter that loses the same move, and both pay fees and slippage).
  An open copy keeps its side. `coin_allowlist` / `coin_blocklist` skip
  opens/adds (`filtered:<coin>`, via `engine.sizing.coin_allowed`); exits are
  never filtered. `paused` is ignored: the sim projects terms, not on/off.
  This is what `GET /api/wallets/{a}/projection` and the trader file's
  what-if replay.
- Optional equity curve: `simulate_wallet(..., curve_step_ms=3_600_000)`
  returns `SimResult.curve = [(t_ms, equity)]` at every step plus the end.
- Not modeled from the engine: `small_account_mode` concentrate (needs their
  full live book), liquidity caps and catch-up orders (need historical
  depth/volume), the daily loss limit.

`runner.prepare_wallet` (fills -> perp filter -> coalesce -> reconstruct ->
HFT gate -> candles) and `runner.simulate_prepared` (raw `SimResult`, skip
flags intact) are shared by `score_one_wallet` and Scout's simstage.

## Score

```
raw = sim_return_pct / max(5, |sim_max_drawdown_pct|) - 10 * liquidations
trusted (>= 5 copies):  score = clamp(raw, -100, 100)
fewer than 5 copies:    score = -200 + clamp(raw, -100, 100) / 100   (in [-201, -199])
not simulated:          score = -200, reason in flags
```

Every wallet with a real sample outranks every `too_few_trades` wallet.
Flags: `vault`, `hft`, `hft_not_simulated`, `too_few_trades`, `liquidated`,
`liquidated:<coin>`, `non_perp_ignored`, `max_leverage_unknown:<coin>`,
`candles_partial:<coin>`, `error:fills_read_failed`, `error:sim:<Exc>`.

## Known biases

- **Copy latency**: inside the 1m tier, entry is the next 1m open + 2 bps
  (we react on the next poll, not their fill). Beyond it, their fill price + 5
  bps. Real 5s polling is closer to their price than "next minute" for
  majors and further for thin HIP-3 markets.
- **Their equity** (proportional mode) is their CURRENT account value from the
  leaderboard for the whole window; their leverage (match mode) is their
  current per-coin leverage. Neither is recoverable historically.
- **No funding** paid or received.
- **Candle resolution liquidation**: the partial bar at entry and at exit is
  not checked (up to 1 bar each: 2 min at 1m, 30 min at 15m). Optimistic.
- **Survivorship**: candidates come from the leaderboard filtered to
  positive 30d and all-time PnL. Wallets that blew up are not in the pool,
  so the ranked set looks better than "a random wallet you might copy".
- **Pre-window positions** are never copied (we never saw the open), which
  matches a copier starting now with `only_new_positions`.
- **Window edge**: with a fresh cache the window ends up to 15 min early.

## Fixed-size cap (sim rule the engine does not have yet)

Found tracing `0x30afce2f` (xyz:DRAM, -127%) and reported on `0xbf732ea0`
(-99.96%, 2 liquidated coins), both at `Settings()` defaults ($1 fixed
margin, max leverage, $100). Cause: `engine.sizing.add_notional` in the
fixed modes scales OUR copy by THEIR fractional add, and the engine then
bumps every sub-minimum add to $10.50. A leader who opens small and scales
in (DRAM: +928%, +77%, ..., then 40+ adds of +0.3% each bumped to $10.50)
takes a $1-margin copy to $100+ of margin; one liquidation then wipes the
account. The sim now caps fixed-mode copies at their fixed size (above),
so one $1-margin copy loses at most its margin plus fees. The live engine
still compounds: `engine.core` needs the same cap to match.

## Runtime

Mainnet, top_n=20, 30 days, $100, `Settings()` (fixed_margin $1, leverage
max), background HL priority, measured 2026-10-04/05:

| run | wall clock | notes |
|---|---|---|
| v1 (top 5, 7 days) | 628s | 1m candles over 7d (HL has 3.5d), no coverage, failed fills read as flat |
| cold, current hl | 1617s | 494 candle calls; ~307k raw fills = ~160 fills pages at 120 weight |
| cold, fills aggregated (scratch venue passing `aggregateByTime`) | 816s | 447 candle calls |
| warm, cache 4.5h old | 165s | one tail fills call per wallet + 46 candle tail calls |
| warm, immediate re-run (< 15 min) | 20s | leaderboard, fills and candles all from cache, 13 candle calls |

Where cold time goes, in order:
1. Fills pages. Every `userFillsByTime` page is charged 120 weight by hl's
   limiter (20 + 2000/20) and busy wallets have 40k-65k raw fills in 30
   days (22-33 pages each). HL's `aggregateByTime: true` merges the partial
   fills of one crossing order: measured 64,241 -> 10,746 fills,
   60,946 -> 7,920, 42,483 -> 10,442. `fills_cache` passes
   `aggregate_by_time=True` as soon as `venue.fills` accepts it;
   `hl.HlVenue.fills` does not yet (needs a contract change). Halves cold.
2. Candle calls (~450 per cold run): spans are fetched per wallet, so a coin
   traded by several wallets is fetched in several pieces at 20 weight
   base each. A two-phase run (all fills first, then one fetch per coin over
   the union of every wallet's spans) is the next cut toward the 3 minute
   cold target.
3. Background priority: discovery may only spend down to 40% of the shared
   bucket, so its sustained rate is the full refill (20/s) only when the
   engine is idle.

Venue calls from one run are serialized (`runner.SerialVenue`): the budget
is the ceiling, and 4 unserialized workers made 120-weight pages queue past
hl's 30s `max_wait` (18 failed reads in one run, now 0).
