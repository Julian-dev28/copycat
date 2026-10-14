# Scout: trader board + trader file pipeline

Spec: `docs/research/copytrading_page_spec.md` (sections 1-3 metrics and Copy
Fit, 5 filters/sorts, 6 contract, 7 caching, 8 routes, 10 tests). The api
imports **only** `discovery.scout.public`.

## Where things run

| Process | What | HL calls |
|---|---|---|
| `python -m discovery.scout serve` | scheduler: stages A/B/C, board builds, on-demand trader files | yes, `COPYCAT_HL_PRIORITY=background`, no agent key |
| api (threadpool) | `scout_page`, `scout_profile`, `scout_fills`, `scout_presets`, `scout_status`: sqlite reads | none |
| api (threadpool) | `scout_what_if`: one sim on cached fills/candles, 1 concurrent | none |
| api (threadpool) | `scout_orders`: live `frontendOpenOrders`, 30 s cache | weight 20 per dex |

`scout_refresh()` and an unknown address in `scout_profile()` only **signal**
`serve` (a `scout_meta.refresh_requested` flag, a `scout_requests` row).
Nothing heavy runs in the api process.

## Public surface (`discovery.scout.public`)

| Function | Returns | Notes |
|---|---|---|
| `scout_page(query)` | `TraderPage` | query = the api dict (`window, preset, coin[], min_av, max_av, min_pnl, max_pnl, style[], min_fit, max_fit, max_dd, min_trips, active_within_h, hide_flagged, q, sort, order, limit, offset`; unset = None). Optional `in_book: [addr]`. Bad value -> `ScoutQueryError` (ValueError). `stale_settings` true when the served board was scored at an older settings hash than `serve` last saw |
| `scout_profile(address)` | `TraderProfile` / `ScoutStatus` / `None` | `ScoutStatus(state="running", stage="stats")` = **build queued, api answers 202**. `None` = invalid address, or the build failed twice (no HL data): 404 |
| `scout_fills(address, before_ms, limit)` | `List[LeaderFillView]` | newest first, strictly before `before_ms`, from the fills cache |
| `scout_orders(address)` | `List[dict]` | live, 30 s cache; `ScoutReadError` on a failed read (never "no orders") |
| `scout_what_if(address, settings, sim_equity_usd, override)` | `WhatIfResult` | `settings.for_leader(address)` patched by `override`; cached fills + candles only; `ScoutBusy` if one is running; `LookupError` if the wallet has no stats |
| `scout_presets()` | `ScoutPresets` | `hip3_count` uses the same predicate as `preset=hip3` (any `dex:COIN` in top 5), so a tab count equals its total |
| | | v18: `copyable` = rows with `sim_copies >= query.COPYABLE_MIN_COPIES` (scoring.MIN_TRUSTED_COPIES, 5) at the served terms, the same predicate as `preset=copyable`; stored in the `scout_rows.sim_copies` column (migration adds it; rows published before carry NULL until the next publish) |
| `scout_status()` | `ScoutStatus` | `refresh_id` = the latest pipeline run; `error` says when `serve` is not running |
| `scout_refresh()` | `ScoutStatus` | queues A+B+C for `serve` (picked up within 10 s); `ScoutBusy` when running or already queued |
| `scout_custom_list()` | `List[CustomWallet]` | v15: wallets added by hand, with `on_board` / `queued` |
| `scout_custom_add(address)` | `CustomWallet` / `None` | v15: adds to `scout_custom` and queues the build (`None` = not an address). Served even mid-refresh, then the board is republished at once |
| `scout_custom_remove(address)` | `bool` | v15: drops the custom row, a universe row that existed only for it, and its served board row (or just the `custom` mark when it is on the leaderboard anyway) |
| `scout_sim_terms_get()` | `ScoutSimTerms` | v16: the stored terms, or the field defaults before any PUT |
| `scout_sim_terms_set(terms)` | `ScoutSimTerms` | v16: stores it (`scout_meta` key `sim_terms`); `serve`'s scheduler re-sims from cache on its next tick |
| `run_scheduler(settings_provider, ...)`, `serve(...)` | blocking | settings and sim terms re-read every tick |

## Pipeline (spec 7.2)

| Stage | When | Work | Weight |
|---|---|---|---|
| A universe | 15 min | stats-data leaderboard via `hl.leaderboard.parse_rows`; AV >= $10k, 30d vlm >= $50k, allTime or 30d PnL > 0, no vaults (`COPYCAT_SCOUT_INCLUDE_VAULTS=1` to keep); top 300 by 30d PnL; book wallets always kept | 0 |
| B stats | 60 min, budgeted | per wallet: see the cadence table below | see below |
| C sim | after B; on a settings OR sim-terms change | `sim.simulate_wallet` on cached fills, candles via the shared cache; Copy Fit over the cohort. A sim-terms-only resim (not `use_live_settings`) runs every wallet it has already simmed before on `CacheOnlyVenue` (zero HL calls; `store.simmed_addresses`) | candles only, 0 on a terms resim |
| publish | after every run | rows -> `scout_rows` under a new `refresh_id`, pointer switched in one transaction | 0 |

### Stage B cadence (indexing tightening, 2026-10)

Before this: every hourly pass re-read `account_state` + `extras` + `userFunding`
+ (re-checked) the liquidation backfill for EVERY wallet, every time, whether
anything about the account had changed or not. Measured live 2026-10-14:
`stage B: budget reached (28595 weight), 177 wallets deferred` -- 124 of 301
wallets refreshed per pass (~230 weight/wallet), 50 minutes, 0.06 wallets/s.
52 board rows sat `stale`.

Now each endpoint has its own cadence; only `portfolio` and the fills tail run
every pass for every wallet:

| Endpoint | Cadence | Trigger to run early |
|---|---|---|
| `portfolio` | every pass | -- |
| fills tail (`fills_cache.sync_fills`) | every pass, incremental | capped at `COPYCAT_SCOUT_MAX_FILLS_PAGES` (default 5) real pages per call: a 53,520-fill wallet's first-ever 30d backfill (27 pages, 3,240 weight in one pass) now costs at most 5 pages (600 weight), the rest next pass (`fills_cache.is_lagging`, flagged `fills_truncated`) |
| `account_state`, `extras`, `userFunding`, liquidation backfill | `COPYCAT_SCOUT_FULL_EVERY_S` (default 6h) | a new fill landed since the last pass (the fills tail's newest timestamp moved), or this is the wallet's first-ever build |

`scout_stats.full_ms` tracks the last time the slow set actually ran per
wallet. On a cheap pass, `account_json`/`positions_json`/`positions_ms` are
carried over unchanged (not re-fetched, not estimated); `extras_unavailable`/
`funding_unavailable` carry over too so a wallet whose reads have been failing
doesn't silently look fine in between full passes. See `stats.build_wallet`'s
docstring for the exact rule.

Per-pass instrumentation: `stats.run_stage_b` logs each wallet's weight by
endpoint and seconds at DEBUG, and an INFO summary (p50/p95 weight, pages,
seconds; the 5 most expensive wallets) after every pass, also stored in
`scout_meta["stage_b_summary"]` (not on the `ScoutStatus` contract -- no
version bump needed for an internal pacing metric; the eval and this README
read it straight from `scout_meta`).

Measured on a throwaway stack (`COPYCAT_SCOUT_UNIVERSE=40`, real Hyperliquid
reads, `stats_budget_check.sh`), see "Tests" below for the exact run.

Custom wallets (contract v15): `scout_custom` holds every address the user
added by hand. Stage A keeps them through the universe swap (source `custom`
when the leaderboard lists them below the cut, `lb` when they are in the top
300 anyway); a wallet the leaderboard has never listed gets its universe row
from stage B (`stats.build_wallet`, account value and window PnL from its own
portfolio, refreshed on every rebuild). The cohort is every `lb`, `book` and
`custom` universe row with stats (`store.BOARD_SOURCES`); `ondemand` rows
(trader files opened by address) still stay off the board. Rows carry
`custom=true`, `preset=custom` filters on `scout_custom`, `ScoutPresets.custom`; `preset=copyable` (v18) keeps the rows the copy-sim could actually follow, `ScoutPresets.copyable` counts them
counts them.

On-demand requests (trader files for untracked wallets, custom wallets just
added) are served by `refresh.service_requests`: between refreshes through
`run_refresh(only=[a])` as before, and DURING a refresh from the scheduler's
progress beat (`refresh.build_one`: stage B then C for that one wallet, no
slot, no progress row), so a request made 2 minutes into a 45-minute refresh
is built in about a minute instead of waiting for the refresh to end. A
custom wallet's build ends with `refresh.republish` (the board rebuilt from
stored stats and sims, no HL call) so its row shows at once. The top-level
service holds the drain guard while it runs, so its own mini refresh's beat
cannot serve the same wallet a second time (it did: every on-demand wallet
was built twice, live 2026-10-14). At start, `scout serve` marks any refresh
row still `running` as failed ("scout restarted"): it is the only process that
runs refreshes, so that row belongs to the process that was killed, and until
this it held the slot for `REFRESH_STALE_S` (15 min) after every restart.

Budget per B pass: `COPYCAT_SCOUT_B_MAX_WEIGHT` (default 28,800 = 40 min at
the ~720/min background share) and `COPYCAT_SCOUT_B_MAX_S` (50 min), charged by
what each wallet actually called (`stats.CountingVenue`). Wallets past the
budget go first next pass (stalest-first ordering + deferral already
guarantees every wallet rotates through within two passes; see
`test_every_wallet_rotates_through_within_two_passes`). With the cheap warm
path, a steady-state pass costs far less per wallet than the pre-tightening
~230 weight/wallet above, so a lot more of the 301-wallet universe fits in
each 40-minute pass -- see the cadence table for the per-endpoint cost.

## Sim terms (contract v16)

The board used to score every wallet at the operator's own live trading
`Settings` (the engine's config) plus `COPYCAT_SCOUT_SIM_EQUITY`. For a
small-account operator that meant the whole leaderboard was simmed at their
size and leverage: $15.20/wallet, exposure target 50x capped to 15x on the
live deployment the night this shipped. 182 of 200 board rows showed Copy Fit
20-29; 104 were capped by a sim liquidation at 15x; 93 had 0 sim copies
because $15 split across a wallet's positions never cleared the $10.50
minimum, landing in `scoring.py`'s `too_few_trades` band (score in
[-201, -199], printed on Discover as "Score -200.00" -- a sort key, not a
grade; see `contracts/models.py` `TraderScore.score`'s docstring). Only 9 rows
were uncapped.

`ScoutSimTerms` (GET/PUT `/api/scout/sim-terms`, `services/api/api/routes/scout.py`)
decouples the board's copy-sim from that config entirely: its own equity,
allocation, leverage (follow-theirs capped, or a fixed Nx -- `leverage` is
both the cap and the fixed value, `to_settings()`'s docstring says why),
margin mode, max worse-entry slippage and small-account handling. Stored in
`scout_meta` (`store.sim_terms`/`set_sim_terms`), **never** `settings.json`:
the engine must never read these, and `use_live_settings=true` is the only
way back to the pre-v16 behavior (every wallet at `Settings.for_leader` +
the env sim equity, unchanged).

**Default terms** (no PUT ever called): $1,000 equity, $100/wallet, exposure
mode `target` fixed at **3x**, isolated, 10% max worse entry (`ScoutSimTerms()`
field defaults). This is NOT the spec's first candidate: the original
proposal was exposure_mode `match` ("follow their leverage") capped at 10x.
Measured instead, offline, against a 40-wallet real-HL discovery.db this
branch had already cached before the real-HL moratorium below started
(`compare_terms.py`/`sweep_terms.py`, scratchpad, zero new HL calls --
`simstage.run_stage_c(allow_cache_only=True)` against addresses already in
`scout_sim`, guarded by a venue stub that raises if anything reaches the
network):

| terms | Fit<=20 / 40 | >=5 sim copies | sim liquidations |
|---|---|---|---|
| match, capped 10x (spec's first candidate) | 40 | 3 | 4 |
| match, capped 5x | 38 | 3 | 1 |
| match, capped 10x, $250/wallet | 39 | 4 | 5 |
| target, fixed 10x | 38 | 8 | 10 |
| target, fixed 5x | 35 | 8 | 4 |
| **target, fixed 3x (the default)** | **15** | **7** | **0** |
| live deployment's own terms ($15.20, target 50x capped 15x) | 38 | 7 | 10 |

`exposure_mode=match` sizes notional off the LEADER's own gross-notional
ratio, so a leader who already runs hot on his own book still produces a
high-risk copy even at a "low" cap number; `exposure_mode=target` controls
notional directly, independent of the leader's own leverage. Lower fixed
leverage monotonically helped here. >= 5 sim copies tops out around 7-8/40
for EVERY terms tried (this specific 40-wallet draw structurally has many
`too_few_trades` wallets -- few enough real round trips in 30d that no
allocation or leverage choice changes it; that is a wallet-population
property of this small sample, not a terms-tuning lever). `min_order_starved`
was 0 for every row in this table: this 40-wallet sample never reproduced the
live deployment's SPECIFIC failure (93/200 starved on the $10.50 minimum at
$15.20) -- a different, smaller, differently-composed sample than the live
300-wallet board. The full-universe live run below is what actually confirms
or revises this; reopen the choice if it does not.

**Full-cohort measurement, 2026-10-15 (297 live board wallets, a read-only
`.backup` of the live `discovery.db`, stage C cache-only, zero HL calls, ~60 s
per terms sheet, 17 s to switch back to an already-simmed sheet):**

| terms (target mode, isolated, $1K equity unless noted) | Fit<=20 / 297 | >=5 sim copies | 0 copies | liquidated cap | sim liquidations | rows with $10.50 skips |
|---|---|---|---|---|---|---|
| $100 @3x concentrate (the default) | 227 | 95 | 115 | 29 | 37 | 167 |
| $250 @3x | 221 | 108 | 104 | 34 | 57 | 179 |
| $500 @3x | 221 | 116 | 100 | 40 | 66 | 183 |
| $1,000 @3x (all in) | 216 | 119 | 95 | 42 | 74 | 190 |
| $500 @5x | 252 | 117 | 96 | 86 | 184 | 188 |
| $1,000 @2x | 209 | 115 | 99 | 28 | 34 | 183 |
| $100 @3x bump | 221 | 113 | 101 | 37 | 57 | 200 |
| $250 @3x bump | 216 | 121 | 95 | 41 | 75 | 210 |
| $1,000 @3x bump | 219 | 127 | 88 | 56 | 95 | 191 |
| $1,000 @3x bump on a $10K account | 220 | 129 | 88 | 56 | 100 | 206 |

Reading: allocation, equity and the bump mode move the copyable set by at
most 34 wallets (95 to 129 with >= 5 sim copies) while every step up buys
more sim liquidations (37 to 100). The ~170 wallets that stay under 5 sim
copies are a population property of the top 300, not a terms lever: 50 are
`inactive` (no fill in 7 d or under $1,000), the rest nibble (a whale with
50-130 open positions adds 0.1% slices that are under $10.50 even on a $3,000
copy notional; median capacity of the skipped rows stays at 9-10% for every
sheet) or trade too rarely. Leverage is the one lever that matters for risk:
5x doubles the liquidated caps of 3x. The default stays $100 @3x concentrate:
the cheapest sheet with the fewest sim liquidations and the same ranking at
the top (the live top 10 at it: Fit 78-85, 5 to 143 copies, 9 of 10 uncapped).
The honest leaderboard is therefore ~100 copyable wallets ranked by copy
result, then ~200 that the row explains ("under the $10.50 minimum at your
size", "only n trades in 30d", inactive), capped at Fit 20-40 so they never
outrank a real copy.

**Real-HL moratorium (as of this writing):** the operator stopped every
throwaway stack's real Hyperliquid reads mid-build (multiple qa2/* sessions'
stacks were running at once, each its own rate bucket on the same IP, and the
live trading engine started seeing 429s -- HL's 1200/min limit is per IP, not
per process). `evals/sim_terms_check.sh`'s end-to-end HTTP run (the GET/PUT
shape checks, the live-deployment-terms vs default comparison over the FULL
build, the "switching back is instant" check) did not finish; the operator
will run it serially after merge. The offline comparison above (reusing an
already-cached real-HL db, zero new calls) is what stands in until then.

**Hash and re-sim.** The board's wanted hash is `refresh.effective_hash`:
`settings_hash(settings, sim_equity)` (unchanged) when `use_live_settings`,
else `refresh.terms_hash(terms)` -- two hash spaces that never collide by
construction, so flipping the switch can never serve a board built under the
wrong terms. `tick()` writes the wanted hash BEFORE running any stage, so a
PUT shows up as `stale_settings=true` within one scheduler tick (<= 10 s),
same as a `Settings` change always did. `scout_sim` rows are kept forever
(never pruned, only `scout_rows`/the pointer history is, `KEEP_REFRESHES=3`),
so switching back to a terms sheet the board has already simmed under is a
republish with zero new sims -- confirmed by
`test_switch_back_to_earlier_terms_is_instant` (0 sims, 0 candle reads) and,
offline, by `compare_terms.py` re-hitting an already-built hash in 0.006-0.033s
for 40 wallets (vs 0.070s/wallet on a hash hit for the first time). The
end-to-end HTTP version of this check is in `evals/sim_terms_check.sh` step 5,
pending the operator's post-merge run (see the moratorium note above).

A terms-only resim (not a `Settings` change) runs every ALREADY-simmed wallet
on `simstage.CacheOnlyVenue` (`store.simmed_addresses`: has a sim at ANY
hash, so its trip-span candles are on disk already -- the sim's position
reconstruction depends on `poll_interval_s`, not on anything in
`ScoutSimTerms`). Measured on the throwaway stack (40-wallet universe, real
HL for the first build, `evals/sim_terms_check.py` / scratch measurement):
**0.070 s/wallet** cached resim, extrapolated **~21 s for 300 wallets** --
nowhere near the ~2-minute budget that would have forced an incremental
"n of 301 simmed" publish; a terms change always re-ranks the FULL board in
one pass. A wallet with no prior sim (a first-ever build, or a brand new
custom wallet) always gets the real venue regardless of `allow_cache_only`,
so a genuine `Settings` change (not a terms change) is completely unaffected:
`allow_cache_only` is only ever true inside the scheduler's own terms-change
re-sim path (`refresh.tick`/`run_refresh`), never for a `Settings`-hash
change.

Progress: `scout_refresh` row (stage, done/total, eta, heartbeat) and
`tail -f /tmp/scout-refresh/progress.log`. The scheduler heartbeat
(`scheduler_heartbeat_ms`, what health and `scout_build().alive` read) is
beaten at every progress step too, so a long refresh never reads as "serve
is not running".

ETA honesty gate (`refresh.eta_s`): no estimate before `COPYCAT_SCOUT_ETA_MIN_DONE`
wallets are done (default 10) OR `COPYCAT_SCOUT_ETA_MIN_FRAC` of the total
(default 10%), whichever clears first. Before this, a pass logged `stage stats
2.3% eta 394m02s | 7/301 rate 0.01/s` -- a number extrapolated from 7 samples,
shown as fact. `ScoutStatus.eta_s` stays `Optional`; the web badge
(`RefreshBadge`) shows `refreshing stats 7/301` with no time until the gate
opens, then `~12m left`.

## Storage

Same WAL file as the rest of discovery, `data/discovery.db`, so B and C fill
the caches manual `/discover` runs read. Scout-owned tables: `scout_universe,
scout_stats, scout_sim, scout_rows, scout_refresh, scout_meta,
scout_requests` (`store.py`). Fills are read only through
`discovery.db.get_cached_fills` (the fills table is that module's to rename,
and it did: `fills` -> `fills_v2`). Last 3 board builds kept.

## Trade history (contract v17, `user_consensus_2026-10.md` Trade history checklist)

Invariants `round_trips`/`build_trips` (`metrics.py`, `thesis/trips.py`) and the
trader-file web tabs hold to, each with a test:

- A flip (long to short with no flat in between, one HL fill crossing zero)
  is a close and a separate open, never one trip (`positions.reconstruct`
  splits it; `test_history_properties.py`'s law test and the real
  `fixtures/history/flip.json` fixture).
- Partial fills, adds and scale-outs aggregate into one trip
  (`fixtures/history/scale_out.json`, a real 95-fill single trip).
- Realized PnL nets fees AND funding accrued during the hold: `net_pnl_usd =
  gross_pnl_usd - fee_usd + funding_usd`. HL's `userFunding.usdc` sign:
  positive = credited (received), negative = debited (paid) -- same
  convention `positions.funding_by_trip` nets with (`fixtures/history/funding_heavy.json`,
  a real 170h hold where funding is ~17% of gross).
- Unrealized PnL on still-open positions is shown separately
  (`TraderPositionView`, the "Positions" tab / "Open now, not in win rate"
  heading on Round trips) and never enters `recent_trips` or win-rate stats:
  `round_trips`/`build_trips` only ever append a trip on a "close" event.
- All times UTC, labeled ("Opened (UTC)", "Time (UTC)", "Placed (UTC)"
  column headers; cells render in UTC, not the viewer's local timezone).
- Deposits/withdrawals stay out of the PnL curve, stay in the account-value
  curve, and the two chart series are never shown with the same label
  (`lib/scout/window.ts` chartData).
- Truncation (`fills_truncated`, HL serves only the newest ~10k fills) is a
  one-line notice at the top of the Round trips and Fills tabs with the
  exact visible count (`TraderScore.fills_30d`), not folded silently into a
  smaller-looking number (`fixtures/history/truncated.json`: a real wallet
  with a documented 21,402-fill/30d population and an 11-day gap).
- A liquidation (`RoundTrip.liquidation`, `LeaderFillView.liquidation`) is
  its own event type -- a visible badge with hover text ("Liquidated by
  Hyperliquid, not closed by the trader"), never an ordinary closed loss.
  Classified from the fill's own `dir` string ("Liquidated ..."), never HL's
  raw per-fill `liquidation` bool: that bool also fires on the COUNTERPARTY
  absorbing someone else's liquidation (an ordinary open), which the
  `history_check` eval caught as 16 false "Liquidated" fills on a wallet
  with exactly 1 real one (fixed in `rows.py fill_view`, see its docstring).
  `fixtures/history/liquidation.json` is the one genuine own-liquidation in
  this whole cached universe, and also carries a real fills-cache duplicate-
  row artifact that `round_trips`/`build_trips` must not fabricate a second
  trip from or lose the real fees to (regression test in the same file).

Gate: `test_positions.py`, `test_scout_metrics.py`, `test_thesis_metrics.py`,
`test_history_properties.py` (hypothesis laws), `test_history_fixtures.py`
(the 5 real fixtures above), `test_scout_profile.py`, `services/api/tests/test_account_history.py`.
Web: `lib/scout/labels.test.ts` (`truncationNotice`), `lib/scout/file/shaping.test.ts`
(demo flip/liquidation scenarios), `lib/account/history.test.ts`, e2e
`tests/demo/trader_file_history.spec.ts` + 2 a11y scans in `tests/a11y/scout.spec.ts`.

Live eval: `services/discovery/evals/history_check.sh [wallet1 wallet2 wallet3]`
-- throwaway stack, real Hyperliquid, defaults to the 3 fixture wallets above
(one with a real liquidation). Per trip: HL closedPnl ties out within 0.5%;
no served trip spans a flip (replays its own fills independently); the
fills-endpoint liquidation count ties out to a direct HL read; funding per
trip ties out to real `userFunding` rows. A partial real run (2026-10-14)
caught the `fill_view` bug above. Every throwaway stack shares Hyperliquid's
per-IP rate limit with the live engine (`COPYCAT_HL_BUCKET_PATH`), so run it
serially with the other live evals.
Last run 2026-10-15 01:12 to 01:25 on 80cf15f, shared live bucket, background
priority: 36/36 PASS on the 3 fixture wallets (48 + 1 + 2 served trips, 3,784
+ 714 + 53 real fills in their spans): every coin's gross PnL tied out to HL
closedPnl to the cent (15 coins on the dense wallet, XPL included under the
half-open span), 0 of 51 trips spanned a flip, liquidation counts 1/1, 0/0,
0/0, and 34 trips with funding tied out to real `userFunding` rows.

## Metric definitions (deterministic, `metrics.py`, `copy_fit.py`)

Spec section 2 formulas, with these documented choices:

- Daily resample = last point of each UTC day that has one. Returns between
  consecutive observed closes; a day whose prior equity < $100 is skipped.
  Ratios are annualised by `sqrt(365 / mean gap days)`: identical to the spec
  for month/week (daily points), correct for the sparse allTime series
  (~1 point per 2-3 days).
- Sharpe and sortino are null below 7 returns (sortino also with no negative day).
- Round trips: raw perp fills (not poll-coalesced: they describe the leader),
  `positions.reconstruct`, flip = close + open, a trip open before the first
  fill or still open is dropped; net = gross (closed_pnl) - fees + funding
  (see "Trade history" above for the full checklist).
- Style from 30d: algo > 100 opens/day, else median hold < 15 min / 24 h /
  7 d; null below 3 trips.
- Account value on the board = leaderboard `accountValue` (all rows from one
  source, refreshed every 15 min). The trader file has the perp/spot/staked split.
- Copy Fit = spec section 3 exactly: percentile parts (ties averaged, nulls 0,
  a lone value 0.5), weights 0.40/0.15/0.10/0.10/0.05/0.10/0.05/0.05, gates
  in order (inactive -> 0, liquidated <= 20, < 5 copies <= 40, hft/vault <= 50,
  fills_truncated warning). Cap flags are listed whenever their condition holds.
- Copy capacity = copies / (copies + min-order skips + every other skipped open).
- Sim curve: exact daily equity from causal prefix runs of
  `simulate_wallet` (30 short runs). Switches to one hourly run automatically
  once `simulate_wallet` accepts `curve_step_ms` and returns `SimResult.curve`.

## CLI

```
python -m discovery.scout serve                     # the scheduler
python -m discovery.scout refresh [--stages ABC] [--limit-b 10] [--limit-c 5] [--partial]
python -m discovery.scout top [--n 20] [--sort fit] [--window 30d]
```

`COPYCAT_SKIP_DOTENV=1` skips `./.env`; `COPYCAT_AGENT_KEY` is always dropped.

## Tests

Gate (offline, ~2.8 s for all 128): `services/discovery/tests/test_scout_*.py`
+ `test_fills_cache.py`: metrics on hand-computed fixtures, Copy Fit
weights/caps/gates, filters and sorts in the api query shape, switchover (old
rows serve while a refresh runs, unswitched rows invisible, retention 3),
single refresh slot, stage-B weight and wall-clock budget, rotation within two
passes, the ETA honesty gate, settings change + `stale_settings`, scheduler
tick, on-demand queue, what-if with zero HL calls. `test_scout_stats_warm.py`:
the warm path itself (cold always full, no-new-fills skips account_state/
extras/funding, a new fill forces a full pass early, the cadence fires
without one, carried-over `extras_unavailable`, a custom wallet's universe
row survives a cheap pass). `test_fills_cache.py`: the per-pass fills page cap
(a dense wallet's capped sync stays contiguous and catches up over later
passes; a sparse wallet costs one call regardless of the cap; uncapped is
byte-for-byte unchanged).
`test_scout_sim_terms.py` (v16):
the model (defaults, validation, `to_settings()`), the store
(`sim_terms`/`set_sim_terms`/`simmed_addresses`), the pure hash/dispatch
functions, and the live pipeline (stale then cache-only resim, instant switch
back, `use_live_settings` never goes cache-only even for already-simmed
wallets, a never-simmed wallet always gets the real venue).

Live eval: `.venv/bin/python -m pytest services/discovery/tests/test_scout_live.py -m live -s`
(stage A + stats for 10 + sim for 5; every metric populated or flagged;
portfolio vs leaderboard 30d PnL within 2% for >= 90%).

Custom wallets, live: `services/discovery/evals/custom_wallet_check.sh [0x<wallet>]`
starts a throwaway api + `scout serve` on a temp data dir (real Hyperliquid
reads, no account, no key, 40-wallet universe), queues a full refresh, adds
the wallet while that refresh runs, and checks the row shows on
`preset=custom` with `custom=true` before the refresh ends, that its file is
served with real account value and sim fields, that `presets.custom` counts
it, and that DELETE takes it off at once. 2 to 6 minutes; exit code = failed
checks. Run it after touching `refresh.service_requests`, `build_one`,
`republish` or the custom store functions.
Last run 2026-10-14 on c851d0b: 12/12 PASS, the row showed 9 s after the add
while the refresh was at stats 0/41 ("built in 4s mid-refresh, board republished").

Stage-B warm path, live: `services/discovery/evals/stats_budget_check.sh [universe]`
(default 40) runs `scout refresh --stages AB` twice back to back on a
throwaway data dir (real Hyperliquid reads, no account, no key): the first
pass is cold (every wallet first-ever built), the second immediately after is
warm (nothing new landed in between). Checks the whole cohort got built cold,
the warm pass's wall clock and weight/wallet (p50) are inside budget, warm is
measurably cheaper than cold, most warm-pass wallets skipped the slow-cadence
set, and the ETA is absent early in a pass then present once the honesty gate
opens. Exit code = failed checks. Run it after touching `stats.build_wallet`,
`fills_cache.sync_fills`'s page cap, or the cadence constants in `config.py`.
Weight is what HL metered for the pages that came back (`HlVenue.last_read`,
billed by `stats.CountingVenue`; `tests/invariants/test_hl_weights.py` pins
it to `hl.rate_limit`'s rule): a warm wallet is portfolio 20 + a one-page
tail at 20 + 1 per 20 rows, about 41. The wall-clock check only means
something ALONE: beside the live scout's own pass every call waits on the
shared bucket.
Last run 2026-10-15 01:25 to 02:42 on 80cf15f, beside the live scout's hourly
pass (shared bucket, background priority), universe 40: 5/7. Cold pass 3,090 s,
23,930 weight (p50 395, pages p50 5.0, 40/40 built, 0 deferred); warm pass
1,493 s, 7,310 weight (p50 140, pages p50 1.0, full set on 15/40); ETA absent
below the gate over 28,776 samples and present after it. Check 3 (warm p50 <=
60) failed on BILLING, not on the path: 140 was exactly portfolio 20 + one
page billed at the 2000-row cap (120) for a tail of a dozen rows; the billing
fix above landed right after this run. Check 2 (warm wall clock <= 240 s) was
bucket wait, not work: 28.8 s per wallet at two calls. Re-run alone after the
fix: see the line below once it lands.

Wall clock on a fresh `COPYCAT_DATA_DIR` (new `hl_rate.bucket`, empty): a
background-priority caller's per-item charge (`rate_limit.charge`) has no
reserve floor, so a few fills/funding pages push the shared bucket well
below the background floor (`COPYCAT_HL_RESERVE_FRAC`, default 0.4 of 1200),
and every acquire after that waits (up to `http_post`'s own 30s `max_wait`)
for refill (20/s) before the next call goes out. Measured 2026-10-14 on a
brand-new throwaway bucket: wallets 1-8 built in well under the 90s/wallet
HL budget, wallet 9 alone took over 90s (`sample` on the process showed it
~70% in `time.sleep` inside `rate_limit.acquire`, the rest in an SSL read of
a large fills response) -- the cold pass was still correctly progressing
(stage B's `done` count kept climbing, no deferral, no failure) when this
session's time budget ran out at stats 13/40, 40-wallet bucket at 450/1200
tokens and climbing. This is the SAME mechanism the indexing ticket exists
to reduce exposure to: fewer slow-cadence endpoint calls per wallet (this
change) means fewer per-item surcharges hitting the bucket, means the warm
pass (which this change makes nearly all portfolio + a 1-page fills tail)
should clear its 40 wallets in well under the 90s/wallet cold rate even
starting from the same depleted bucket -- but that specific comparison was
not captured end-to-end in one session; re-run the script (ideally when
nothing else on this host is drawing background HL weight) for the full
recorded PASS/FAIL. `test_scout_stats_warm.py` and `test_fills_cache.py`
(gate, deterministic, no live dependency) prove the mechanism itself: no
account_state/extras/funding call on a no-new-fill warm pass, a new fill or
the cadence forcing one right away, and the fills page cap staying
contiguous and catching up over later passes.

Sim terms, live: `services/discovery/evals/sim_terms_check.sh` starts the same
kind of throwaway stack (universe 40, real HL), waits for the first build,
PUTs the live deployment's own terms ($15.20/wallet, exposure target 50x
capped 15x), checks the board re-ranks and the Fit distribution is worse than
the default terms (more rows at Fit <= 20, fewer with >= 5 sim copies, more
starved on the $10.50 minimum), PUTs the default terms back, checks switching
to an already-simmed hash is near-instant, and checks PUT validates like
LeaderOverride (422 on a bad value). 2 to 6 minutes solo; exit code = failed
checks. Run it after touching `ScoutSimTerms`, `refresh.effective_hash`/
`terms_hash`, `simstage.run_stage_c`'s cache-only path, or the sim-terms
store/api functions.
Last run 2026-10-15 00:49 on e76615c, shared live bucket, background priority: 9/13 PASS, inconclusive. GET/PUT shapes, the documented default and both 422 validations passed; the four failures share one cause: the throwaway stack's first 40-wallet build had not finished after 601 s because the live scout's own hourly stats pass was drawing the same per-IP HL budget at the same time, so no sim existed to re-rank or switch back to (the three comparison checks passed on 0 vs 0). Re-run alone, between live stats passes (`/api/scout/status` idle), for the recorded verdict.
Second run 2026-10-15 02:42 on 80cf15f (serial after history and budget, same shared bucket) was killed by the operator session's 2 h background limit 30 minutes into the first build, right after the budget eval had measured a 40-wallet cold stage B at 3,090 s beside the live pass. `COPYCAT_SIM_TERMS_REFRESH_WAIT_S` now overrides the 2,400 s first-build wait for a run beside a live stack.
