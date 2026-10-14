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
| B stats | 60 min, budgeted | per wallet: `portfolio` + `account_state` + `extras` + incremental fills sync (discovery's fills cache). All-or-nothing per wallet; 2 failures in a row -> sits out a cycle, row flagged `stale`. Order: book, on-demand, stalest, then universe rank | ~170 warm, ~340 cold (measured) |
| C sim | after B; on a settings OR sim-terms change | `sim.simulate_wallet` on cached fills, candles via the shared cache; Copy Fit over the cohort. A sim-terms-only resim (not `use_live_settings`) runs every wallet it has already simmed before on `CacheOnlyVenue` (zero HL calls; `store.simmed_addresses`) | candles only, 0 on a terms resim |
| publish | after every run | rows -> `scout_rows` under a new `refresh_id`, pointer switched in one transaction | 0 |

Custom wallets (contract v15): `scout_custom` holds every address the user
added by hand. Stage A keeps them through the universe swap (source `custom`
when the leaderboard lists them below the cut, `lb` when they are in the top
300 anyway); a wallet the leaderboard has never listed gets its universe row
from stage B (`stats.build_wallet`, account value and window PnL from its own
portfolio, refreshed on every rebuild). The cohort is every `lb`, `book` and
`custom` universe row with stats (`store.BOARD_SOURCES`); `ondemand` rows
(trader files opened by address) still stay off the board. Rows carry
`custom=true`, `preset=custom` filters on `scout_custom`, `ScoutPresets.custom`
counts them.

On-demand requests (trader files for untracked wallets, custom wallets just
added) are served by `refresh.service_requests`: between refreshes through
`run_refresh(only=[a])` as before, and DURING a refresh from the scheduler's
progress beat (`refresh.build_one`: stage B then C for that one wallet, no
slot, no progress row), so a request made 2 minutes into a 45-minute refresh
is built in about a minute instead of waiting for the refresh to end. A
custom wallet's build ends with `refresh.republish` (the board rebuilt from
stored stats and sims, no HL call) so its row shows at once.

Budget per B pass: `COPYCAT_SCOUT_B_MAX_WEIGHT` (default 28,800 = 40 min at
the ~720/min background share) and `COPYCAT_SCOUT_B_MAX_S` (50 min), charged by
what each wallet actually called (`stats.CountingVenue`). Wallets past the
budget go first next pass. A cold 300-wallet universe needs ~4 passes; warm
passes cover ~170 wallets.

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

## Storage

Same WAL file as the rest of discovery, `data/discovery.db`, so B and C fill
the caches manual `/discover` runs read. Scout-owned tables: `scout_universe,
scout_stats, scout_sim, scout_rows, scout_refresh, scout_meta,
scout_requests` (`store.py`). Fills are read only through
`discovery.db.get_cached_fills` (the fills table is that module's to rename,
and it did: `fills` -> `fills_v2`). Last 3 board builds kept.

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
  fill or still open is dropped; net = closed_pnl - fees.
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

Gate (offline, a few seconds): `services/discovery/tests/test_scout_*.py`:
metrics on hand-computed fixtures, Copy Fit weights/caps/gates, filters and
sorts in the api query shape, switchover (old rows serve while a refresh runs,
unswitched rows invisible, retention 3), single refresh slot, stage-B weight
and wall-clock budget, settings change + `stale_settings`, scheduler tick,
on-demand queue, what-if with zero HL calls. `test_scout_sim_terms.py` (v16):
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
Last run: PENDING -- stopped mid-build by the operator (real-HL moratorium,
see "Sim terms" above: concurrent qa2/* throwaway stacks were pushing the
shared-IP HL rate limit into 429s for the live trading engine). The script is
correct and in the branch; the operator runs it serially after merge. Until
then, the "Default terms" table above (offline, zero new HL calls, reusing a
discovery.db this branch had already built) is the evidence for the default
choice, and `test_scout_sim_terms.py` covers the hash/dispatch/cache-only
logic this eval would otherwise be the only check on.
