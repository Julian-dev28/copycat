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
| `run_scheduler(settings_provider, ...)`, `serve(...)` | blocking | settings re-read every tick |

## Pipeline (spec 7.2)

| Stage | When | Work | Weight |
|---|---|---|---|
| A universe | 15 min | stats-data leaderboard via `hl.leaderboard.parse_rows`; AV >= $10k, 30d vlm >= $50k, allTime or 30d PnL > 0, no vaults (`COPYCAT_SCOUT_INCLUDE_VAULTS=1` to keep); top 300 by 30d PnL; book wallets always kept | 0 |
| B stats | 60 min, budgeted | per wallet: `portfolio` + `account_state` + `extras` + incremental fills sync (discovery's fills cache). All-or-nothing per wallet; 2 failures in a row -> sits out a cycle, row flagged `stale`. Order: book, on-demand, stalest, then universe rank | ~170 warm, ~340 cold (measured) |
| C sim | after B; on settings change | `sim.simulate_wallet` on cached fills, candles via the shared cache; Copy Fit over the cohort | candles only |
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

Settings: the board is scored at `settings_hash(settings, sim_equity)`
(Settings minus enabled/dry_run/leaders/contract_version, plus sim equity,
default `COPYCAT_SCOUT_SIM_EQUITY=1000`). On a change the old board keeps
serving with `stale_settings=true` until C has re-simulated every wallet.

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
trip ties out to real `userFunding` rows. See `history_check.sh`'s own header
for the current run status: a partial real run (2026-10-14) already caught
and the branch already fixes the `fill_view` bug above; a clean full run is
PENDING, serial, by the operator after the qa2 branches merge (every
throwaway stack shares Hyperliquid's per-IP rate limit with the live engine).

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

Gate (offline, ~1.6 s for all 59): `services/discovery/tests/test_scout_*.py`:
metrics on hand-computed fixtures, Copy Fit weights/caps/gates, filters and
sorts in the api query shape, switchover (old rows serve while a refresh runs,
unswitched rows invisible, retention 3), single refresh slot, stage-B weight
and wall-clock budget, settings change + `stale_settings`, scheduler tick,
on-demand queue, what-if with zero HL calls.

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
