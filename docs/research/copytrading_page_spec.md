# Trader discovery page: spec

2026-10-04. Research + spec only, no code changed. Goal: give copycat a trader
leaderboard and trader profile page with the same feature set as the
reference copy-trading discovery page on hyperdash.com, built on our own
design, naming and data pipeline. Nothing from their branding, logo, copy
text or visual identity is reused. Their product name does not appear in our
UI or code.

Working names (ours): page = **Scout**, list = **Scout board**, detail =
**Trader file**, score = **Copy Fit** (0 to 100). Route `/scout` in
services/web.

## 0. How this was captured

Read only, in the operator's own Chrome (Claude in Chrome). No login, no
wallet action, no form submitted, no copy button pressed. Captured
2026-10-03/04:

- `https://hyperdash.com/copytrading` (card grid, list toggle, sort menu,
  filter chips, preset tabs).
- One trader detail page (`/address/0x051c...693c`).
- Network: `performance.getEntriesByType('resource')` plus the page's GraphQL
  cache (`getSystemGroupTraders({"groupId":"copytraders"})`, 100 rows).
- Their public docs: docs.hyperdash.com/copy-trade and /wallet-explore.

### 0.1 Endpoints the page calls

| Endpoint | What it is | Reproducible by us |
|---|---|---|
| `api.hyperliquid.xyz/info` | HL public info API, direct from the browser | yes, same API |
| `h.hyperdash.com/info` | their proxy/cache in front of HL `/info` | yes, we call HL directly through services/hl |
| `api.hyperdash.com/graphql` op `getSystemGroupTraders(groupId)` | the ranked list. groups seen: `copytraders`, `tagged` | **internal**: precomputed server side. Every field is derivable from HL data except `copyScore` (opaque), `label`/`verified`/`twitter`/`avatar` (their curation) |
| `api.hyperdash.com/api/hyperliquid/market-stats`, `market-catalog` | coin list, icons, 24h stats | yes: HL `metaAndAssetCtxs` + `perpDexs` |
| `hyperdash.com/_serverFn/<hash>` | SSR server function (TanStack Start) | n/a |
| `p.hyperdash.com/*` | product analytics + feature flags | n/a, we skip |
| `api.hyperdash.com/api/auth/*` | session | n/a, we have no accounts |

No call to `stats-data.hyperliquid.xyz` from the browser. Their list is a
server-side job. That matches our plan: precompute in discovery, serve from
sqlite.

### 0.2 Row shape of their list item (field names only)

`address, label, verified, displayName, avatar, twitter, lastTradeAt,
lastFillAt, portfolioGraph[{timestamp, value}] (45 to 56 pts over 30d,
starts at 0, i.e. a cumulative PnL series, same granularity as HL
portfolio "month" pnlHistory), pnl, perpsEquity, winrate, pnlCohort,
sizeCohort, totalTrades, totalLongTrades, totalShortTrades,
totalWinningTrades, totalLosingTrades, sharpe, drawdown, copyScore, tag,
topAssets[{coin, volume, pnl}] (up to 5)`.

Distribution over the 100 rows: tag swing 74, intraday 17, position 7, scalp
1; copyScore median 74, max 92; 7 rows score exactly 0, all of them either
zero equity or no fill for 5+ days (gate, not a blend). Pearson correlation
of copyScore (non-zero rows) with: log10 pnl 0.43, recency 0.36, log10
equity 0.34, sharpe 0.24, win rate 0.23, drawdown 0.19, 30d ROI -0.30. So
their score is mostly "large, recently active, profitable, smooth"; it does
not look at what a small copier would actually earn. That gap is our edge.

Their docs: score "weights consistency, drawdown, and trade frequency
alongside raw PnL". Formula not published. We do not try to clone it.

### 0.3 List page features (theirs)

- Hero strip of 3 featured traders.
- Preset tabs: Top 100, Equities focused, Top BTC, Top HYPE, Top CL (crude
  oil, a HIP-3 market). Per-asset presets.
- Sort menu: highest copy score, highest ROI, highest equity, lowest equity,
  recently active.
- `$` / `%` toggle for the PnL figure.
- Grid view (cards) / list view toggle.
- Filters: account value (min/max USD), PnL (min/max USD), trading style
  (all, algo, scalp, intraday, swing, position), copy score (0 to 100
  range). Explore page adds a time window (1d, 7d, 30d, all; default 7d).
- Card: avatar, name or short address, icons of top traded assets, "last
  active N ago", 30d PnL (or ROI %), equity, 30d PnL sparkline (green above
  zero, red below), score as N/100 with a 10-segment bar, copy button.

### 0.4 Detail page features (theirs)

- Left rail: identity, track / view-as buttons, copy score panel with copy
  button, account value, account equity split (perps / spot / staked),
  overview (unrealized PnL, account leverage, margin usage, all-time PnL,
  volume), analysis (longest win streak in days, trading style, avg trade
  duration, median trade duration, PnL cohort, size cohort), performance
  block with window select (drawdown, win rate, sharpe, sortino).
- Top tiles: performance (PnL, win rate bar, trade count), leverage
  (notional vs equity), margin usage (free margin, % from liquidation),
  direction bias (long $ vs short $, labelled e.g. "very bullish").
- Main chart: perps / combined / calendar tabs; PnL vs value toggle; 24h,
  7d, 30d, all windows.
- Tabs: positions (asset, lev, size, value, entry, mark, PnL and ROE,
  liquidation px, margin, funding), balances, predictions, orders, fills,
  trades, TWAP, transfers, performance.
- Right rail: live activity feed of fills ("$24.98K AAVE long reduced, 139.5
  AAVE @ 178.8, +$13.5K").
- Copy flow (from their docs, not clicked): copy or counter-trade, up to 10
  traders with equal or custom weight, max position leverage 1 to 40x
  (default 20x), new positions only, max worse entry (default 10%, max
  50%), include spot/staked HYPE in sizing, asset allow/deny list, minimum
  $100 funding, builder fee. Single-trader view projects 30d PnL onto a
  $1,000 allocation.

Most of that copy flow already exists in our `Settings` /
`LeaderOverride` (leaders max 10, `max_position_leverage`,
`only_new_positions`, `max_worse_entry_pct`, `include_spot_staked`, sizing
modes, per-leader overrides). Missing on our side: counter-trade mode and
the asset allow/deny list (see section 9).

## 1. What they show vs what we will show

| Theirs | Ours | Source / note |
|---|---|---|
| Copy score 0-100, opaque | **Copy Fit** 0-100, formula published on the page, per-part breakdown | section 3 |
| 30d PnL $ / ROI % | same, plus 1d / 7d / all-time windows | stats-data leaderboard |
| PnL sparkline | 30d PnL sparkline **plus** a second line: our copy-sim equity at the user's settings | portfolio + sim |
| "Project 30d onto $1,000" | "If you had copied with *your* settings and *your* equity" sim curve, fees, skipped orders, liquidations | existing discovery sim |
| Win rate, trades, long/short counts | same, defined on closed round trips | userFillsByTime |
| Sharpe, sortino, drawdown | same, from daily PnL / account value | portfolio |
| Trading style tag | same five buckets, our thresholds | fills |
| PnL cohort / size cohort | **PnL tier / size tier**, our names and thresholds | leaderboard |
| Top assets | same (coin, volume, PnL) | fills |
| Last active | same | fills cache |
| Positions, lev, liq, margin, funding | same | clearinghouseState |
| Account leverage, margin usage, % from liq, direction bias | same | clearinghouseState |
| Longest win streak, avg / median hold | same | portfolio + fills |
| Calendar of daily PnL | same | portfolio |
| Live fill feed | polled recent fills, 30s refresh on open page only | userFillsByTime |
| Followers / copiers count, AUM copied | **not shown**. We have no user base to count. Substitutes below | n/a |
| Labels, verified, twitter, avatar | HL `displayName` from leaderboard only; plus a local operator note per address | ours |
| Balances, orders, TWAP, transfers, predictions tabs | orders + funding only in v1; rest dropped | optional |
| Featured hero carousel | dropped. Top 3 by Copy Fit pinned as the first row | design choice |

Honest substitutes for follower count:
1. **In your book**: badge when the address is in `Settings.leaders`.
2. **Copy capacity**: share of his 30d opens that our sim could actually
   execute at the user's settings (`sim_copies / (sim_copies + skipped)`).
   This answers "can I even follow him at my size", which follower counts
   never did.
3. For HL vaults only: `vaultDetails.followers` length is public, show it
   with a "vault depositors" label. Never present it as copiers.

## 2. Metric table

Weights are HL `/info` weights as encoded in `services/hl/hl/rate_limit.py`
(`userFillsByTime` = 20 + ceil(items/20)). HL budget is 1200 weight/min per
IP; the shared limiter keeps ~40% for the engine, so discovery gets ~720/min.
The stats-data leaderboard is a separate host with no `/info` weight: one GET
(~47k rows, ~25 MB) per refresh.

"W" = which window the metric is computed for. All money in USD, percent as
percent (10.0 = 10%), timestamps epoch ms, matching `contracts/models.py`.

| # | Metric | Definition | Formula | HL source | Weight / wallet |
|---|---|---|---|---|---|
| 1 | PnL (day/week/month/allTime) | HL's own window PnL | `windowPerformances[w].pnl` | stats-data leaderboard | 0 (shared GET) |
| 2 | ROI (same windows) | HL's own window ROI | `roi * 100` | stats-data leaderboard | 0 |
| 3 | Volume (same windows) | traded notional | `vlm` | stats-data leaderboard | 0 |
| 4 | Account value | perp equity, main + HIP-3 dexes | `sum(marginSummary.accountValue)` over active dexes | clearinghouseState per dex (already `Venue.account_state`) | 2 x dexes (2 to 6) |
| 5 | Equity split | perps / spot / staked HYPE | perps from #4; spot + staked from `Venue.extras` | spotClearinghouseState, delegatorSummary | 2 + 2 |
| 6 | PnL curve (24h/7d/30d/all) | cumulative PnL series | `portfolio[w].pnlHistory` as `[t_ms, pnl]` | **portfolio** (new Venue method) | 20 |
| 7 | Account value curve | equity series | `portfolio[w].accountValueHistory` | portfolio (same call) | 0 extra |
| 8 | Daily return r_d | PnL of day d over prior equity | resample pnlHistory to UTC day closes; `r_d = (P_d - P_{d-1}) / AV_{d-1}`; skip day if `AV_{d-1} < 100` | portfolio | 0 extra |
| 9 | Max drawdown (W) | worst peak to trough of the return index | `I_0 = 1; I_d = I_{d-1} * (1 + r_d); DD = min_d(I_d / max_{k<=d} I_k - 1) * 100` (reported as positive %) | portfolio | 0 extra |
| 10 | Sharpe (W) | annualised mean/stdev of daily returns, rf = 0 | `mean(r) / stdev(r, ddof=1) * sqrt(365)`; null if fewer than 7 days or stdev = 0 | portfolio | 0 extra |
| 11 | Sortino (W) | same, downside deviation | `mean(r) / sqrt(mean(min(r,0)^2)) * sqrt(365)`; null if no negative day | portfolio | 0 extra |
| 12 | Profitable days % | consistency | `count(r_d > 0) / count(days) * 100` | portfolio | 0 extra |
| 13 | Longest win streak (days) | max run of consecutive `r_d > 0` | linear scan | portfolio (allTime series) | 0 extra |
| 14 | Calendar | daily PnL per UTC day | `P_d - P_{d-1}` | portfolio | 0 extra |
| 15 | Round-trip trades | flat to flat per coin (flip = close + open, existing `positions.reconstruct`) | count of `close` events in W | userFillsByTime (fills cache) | 20 + ceil(n/20) per page, incremental |
| 16 | Win rate (W) | share of round trips with positive net PnL | trip net = `sum(closed_pnl) - sum(fee)` over the trip's fills; `wins / trips * 100` | fills | 0 extra |
| 17 | Long / short trade count | trips by side | from trip side | fills | 0 extra |
| 18 | Avg / median hold | trip duration | `close_ms - open_ms`, trips fully inside W (existing `median_hold_hours`, add mean) | fills | 0 extra |
| 19 | Opens per day | activity | existing `positions.opens_per_day` | fills | 0 extra |
| 20 | Trading style | bucket | algo if opens/day > 100 (existing `hft` flag); else by median hold: scalp < 15 min, intraday < 24 h, swing < 7 d, position >= 7 d; null if fewer than 3 trips | fills | 0 extra |
| 21 | Top assets | top 5 coins | per coin: volume `sum(px*sz)`, PnL `sum(closed_pnl - fee)`; rank by volume | fills | 0 extra |
| 22 | Last active | last fill | `max(time_ms)` in fills cache | fills | 0 extra |
| 23 | Open positions | coin, side, size, notional, entry, mark, uPnL, ROE %, lev, cross/iso, liq px, margin, funding since open | `assetPositions[].position` (`szi, entryPx, positionValue, unrealizedPnl, returnOnEquity, leverage, liquidationPx, marginUsed, cumFunding.sinceOpen`) | clearinghouseState (already in `raw_positions`) | 0 extra over #4 |
| 24 | Account leverage | gross notional over equity | `sum(abs(positionValue)) / accountValue` | clearinghouseState | 0 extra |
| 25 | Margin usage | `totalMarginUsed / accountValue * 100` | | clearinghouseState | 0 extra |
| 26 | Distance to liquidation | closest position | `min over positions of abs(mark - liqPx) / mark * 100`; null if no liq px | clearinghouseState | 0 extra |
| 27 | Direction bias | long share of gross notional | `long_ntl / (long_ntl + short_ntl) * 100`; label: >= 80 strongly long, 60 to 80 long, 40 to 60 balanced, 20 to 40 short, < 20 strongly short | clearinghouseState | 0 extra |
| 28 | Size tier | by account value | S < 10k, M 10k to 100k, L 100k to 1M, XL 1M to 10M, XXL >= 10M | #4 | 0 |
| 29 | PnL tier | by allTime PnL | losing < 0, up 0 to 100k, strong 100k to 1M, elite >= 1M | #1 | 0 |
| 30 | Copy sim (existing) | what copying him would have earned at the user's settings and equity | `sim.simulate_wallet` -> return %, max DD %, liquidations, copies, skipped min order, fees | fills + candleSnapshot (shared per coin cache) | candles amortised across wallets |
| 31 | Sim curve (new) | equity of the simulated copier per hour | emit `(t_ms, equity)` from `_walk_candles` at each hour boundary | same | 0 extra |
| 32 | Copy capacity | share of his opens we could execute | `sim_copies / (sim_copies + sim_skipped_min_order + other skips)` | sim | 0 extra |
| 33 | Open orders (detail only) | resting orders | `frontendOpenOrders` | 20, on demand |
| 34 | Funding paid (detail only) | 30d funding | `userFunding` sum of `usdc` | 20 + ceil(n/20), on demand |

**Cannot reproduce**: follower / copier counts, AUM copied, their curated
labels, verified badge, avatars, twitter handles. Substitutes in section 1.

Caveats to state in tooltips (deterministic, not hidden):
- Leaderboard "month" is HL's bucket, not a strict trailing 30d (already
  documented in `leaderboard.py`).
- `userFillsByTime` only reaches the most recent 10,000 fills; for an algo
  wallet the 30d trip stats can be truncated. Flag `fills_truncated` when the
  oldest cached fill is newer than the window start.
- Trips open before the window or still open are excluded from hold/win
  stats (undercount, never fabricated).
- `pnlHistory` excludes deposits/withdrawals, so drawdown and sharpe are not
  distorted by transfers. `accountValueHistory` is not, so the value chart
  shows transfers as steps; label it "account value", not "performance".

## 3. Copy Fit: how their style of metric combines with our sim

Our existing `TraderScore.score` (sim return / max(5, |sim DD|), minus 50 per
liquidation, x0.2 below 5 copies) answers the right question: what would *I*
have made. It is unbounded and settings-dependent, which makes it a poor
display number and unstable across runs. Their copyScore is bounded and
readable but ignores the copier. Copy Fit keeps our sim as the dominant term
and adds the trader-quality terms that make it legible.

Computed in `services/discovery/discovery/copy_fit.py` (pure function, no
I/O), over the scored cohort of one refresh:

```
pct(x) = percentile rank of x within the cohort, 0..1 (ties averaged, nulls -> 0)

parts = {
  "sim":         pct(sim_score),                    weight 0.40
  "sharpe":      pct(sharpe_30d),                   weight 0.15
  "drawdown":    pct(-max_drawdown_30d_pct),        weight 0.10
  "consistency": pct(profitable_days_pct_30d),      weight 0.10
  "win_rate":    pct(win_rate_30d_pct),             weight 0.05
  "sample":      min(1, log10(1 + trips_30d) / log10(1 + 50)),   weight 0.10
  "capacity":    copy_capacity,                     weight 0.05
  "recency":     1 if last fill < 24h, linear to 0 at 7d,        weight 0.05
}
fit = 100 * sum(w * part)
```

Gates and caps, applied after the blend, in order (each adds a flag):

| Condition | Effect | Flag |
|---|---|---|
| account value < $1,000 or no fill in 7d | fit = 0 | `inactive` |
| `sim_liquidations > 0` | fit = min(fit, 20) | `liquidated` (existing) |
| `sim_copies < 5` | fit = min(fit, 40) | `too_few_trades` (existing) |
| style = algo (`hft`) | fit = min(fit, 50) | `hft` (existing): we poll every 5s, we cannot follow him |
| vault | fit = min(fit, 50) | `vault` (existing) |
| `fills_truncated` | no cap, warning shown | `fills_truncated` |

Why percentiles: they make the blend unit-free, so a 300% ROI outlier cannot
swamp sharpe, and Copy Fit stays in 0..100 without hand-tuned scaling.
Trade-off: a trader's fit moves when the cohort changes. The page states the
cohort ("ranked among 280 traders, refreshed 12 min ago").

Why sim gets 0.40: it is the only term that includes the user's equity,
sizing mode, leverage mode, min-order skips and fees. The rest describe the
leader. The weights are a starting point; section 8 has the eval that tunes
them on forward returns, not on taste.

The per-part numbers are stored and rendered as a stacked bar on the trader
file ("why this score"), extending the existing `lib/scoreExplain` in web.

Settings dependence: `sim` and `capacity` depend on the user's `Settings` and
sim equity. The list is computed for the current saved settings
(`settings_hash`). When settings change, a sim-only rescore runs from cached
fills and candles (zero new fills weight, candles only for new coins).

## 4. Page layout (our design)

Follow the existing services/web design system (`components/ui/Panel`,
`Badge`, `Button`, `AddressChip`, `lib/format`), its colour tokens and type
scale. No dark-green score footer, no 10-segment bar, no hero carousel, no
"Copytrade" wording. Our verbs: **Add to book** / **In book**.

### 4.1 Scout board (`/scout`)

```
┌ Scout ───────────────────────────────── refreshed 12m ago · 280 ranked · [Refresh] ┐
│ Presets: [All] [HIP-3 equities] [BTC] [ETH] [HYPE] [SOL] [+ coin…]                 │
│ Window: (1d)(7d)(30d)(All)   Sort: [Copy Fit ▾]   PnL: [$|%]   View: [Table|Cards] │
│ Filters: Account value [min-max]  PnL [min-max]  Style [any ▾]  Copy Fit [0-100]  │
│          Max DD ≤ [ ]%  Min trips [ ]  Active within [7d ▾]  [ ] hide flagged       │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Table (default on desktop):                                                        │
│ # │ Trader │ Fit │ Sim ret │ Sim DD │ PnL(W) │ ROI(W) │ Sharpe │ DD │ Win% │ Trips │
│   │ Style │ Size tier │ Top coins │ Last active │ Curve(30d) │ [Add to book]       │
│ Row expand: copy capacity, liquidations, fees, flags with plain-language reasons    │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Cards (default on phone): name/addr, style chip, top coins, last active,           │
│ PnL(W), equity, dual-line sparkline (his PnL + your sim), Fit number + 3 top parts │
└────────────────────────────────────────────────────────────────────────────────────┘
```

- Default sort: Copy Fit desc. Default window: 30d. Table on desktop, cards
  under 640 px (the existing DiscoveryTable already has a phone layout).
- Sparkline: his 30d PnL in a neutral line, our sim equity in the accent
  line, both normalised to 0 at window start.
- Presets are generated from data, not hardcoded: "HIP-3 equities" = traders
  whose top-asset volume is >= 50% on `xyz:` coins; coin chips = the 6 coins
  with the most traders having them as #1 asset, plus a coin picker.
- Empty and stale states: no refresh yet -> show the CTA to start one; last
  refresh older than 3x the schedule -> amber "stale" banner.

### 4.2 Trader file (`/scout/[address]`)

```
┌ header: name / AddressChip · style chip · size tier · PnL tier · [Add to book] [Open in HL explorer] ┐
├ left column ─────────────┬ main ─────────────────────────────────────────────┬ right ────────────┤
│ Copy Fit 78              │ Tiles: PnL(W)+win rate+trips │ Leverage │ Margin   │ Recent fills      │
│  stacked part bar        │        use + % to liq │ Direction bias            │ (poll 30s while   │
│  "why" list              │                                                   │  page is open)    │
│ Your copy (sim)          │ Chart tabs: [His PnL] [Account value] [Your sim]  │                   │
│  return, DD, liqs,       │            [Calendar]   window 24h/7d/30d/All    │                   │
│  fees, capacity,         │                                                   │                   │
│  "re-run with…" settings │ Tabs: Positions │ Trades │ Fills │ Coins │ Orders  │                   │
│ Account                  │        │ Funding                                  │                   │
│  value, perps/spot/stake │                                                   │                   │
│ Stats (window select)    │                                                   │                   │
│  DD, sharpe, sortino,    │                                                   │                   │
│  win %, profitable days, │                                                   │                   │
│  longest streak, avg /   │                                                   │                   │
│  median hold, opens/day  │                                                   │                   │
└──────────────────────────┴───────────────────────────────────────────────────┴───────────────────┘
```

- **Your copy** panel is the differentiator. It shows the sim at the saved
  settings and a small form (sizing mode, multiplier, leverage mode, equity)
  that POSTs to the what-if route and redraws the sim curve. It never writes
  settings. **Add to book** writes via the existing `POST /api/leaders` and,
  if the user changed the what-if fields, offers to save them as a
  `LeaderOverride` through `PATCH /api/settings`.
- Positions tab columns: coin, side, lev (cross/iso), size, notional, entry,
  mark, uPnL (ROE %), liq px, distance to liq %, margin, funding since open.
- Trades tab: reconstructed round trips: coin, side, opened, closed, hold,
  entry avg, exit avg, max notional, net PnL, win/loss.
- Coins tab: per-coin volume, PnL, trips, win rate (top assets, full list).
- Phone: single column, left panels collapse into an accordion above the
  chart, right rail becomes a "Recent fills" tab.

## 5. Filters and sorts

All server side, translated to indexed SQL on `scout_rows` (section 7).

Filters (query params on `GET /api/scout/traders`):

| Param | Type | Meaning |
|---|---|---|
| `window` | `1d,7d,30d,all` | which PnL/ROI/volume window the PnL columns and PnL filter use (stats metrics use 30d in v1; 7d/all added once cheap) |
| `preset` | `all,hip3,coin:<COIN>` | preset tab |
| `coin` | repeatable | has this coin in top assets |
| `min_av`, `max_av` | USD | account value |
| `min_pnl`, `max_pnl` | USD | PnL in `window` |
| `style` | repeatable `algo,scalp,intraday,swing,position` | trading style |
| `min_fit`, `max_fit` | 0..100 | Copy Fit |
| `max_dd` | % | 30d max drawdown |
| `min_trips` | int | 30d round trips |
| `active_within_h` | int | last fill within N hours |
| `hide_flagged` | bool | drop rows with liquidated/hft/vault/inactive |
| `q` | text | address prefix or display name |
| `limit`, `offset` | int | paging, limit max 200 |

Sorts (`sort` + `order`): `fit` (default), `sim_return`, `sim_dd`, `pnl`,
`roi`, `account_value`, `sharpe`, `max_dd`, `win_rate`, `trips`,
`last_active` (recently active), `volume`. Covers all five of their sorts
(score, ROI, equity high/low, recently active) plus ours.

## 6. Contract changes (`contracts/models.py`, bump `CONTRACT_VERSION` to 3)

Contract change touches discovery, api, web types
(`services/web/src/lib/api/types.ts`, regenerated from `openapi.json`). One
commit, all sides.

```python
class PnlWindow(str, Enum):
    day = "1d"; week = "7d"; month = "30d"; all_time = "all"

class TradingStyle(str, Enum):
    algo = "algo"; scalp = "scalp"; intraday = "intraday"; swing = "swing"; position = "position"

class SizeTier(str, Enum):   S = "S"; M = "M"; L = "L"; XL = "XL"; XXL = "XXL"
class PnlTier(str, Enum):    losing = "losing"; up = "up"; strong = "strong"; elite = "elite"

class CurvePoint(BaseModel):
    t_ms: int
    value: float                         # USD

class WindowPerf(BaseModel):             # straight from the stats-data leaderboard
    window: PnlWindow
    pnl_usd: float
    roi_pct: float
    volume_usd: float

class RiskStats(BaseModel):              # from portfolio pnl/accountValue history
    window: PnlWindow
    max_drawdown_pct: Optional[float] = None    # >= 0
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    profitable_days_pct: Optional[float] = None
    days: int = 0

class TradeStats(BaseModel):             # from reconstructed round trips
    window: PnlWindow
    trips: int
    wins: int
    long_trips: int
    short_trips: int
    win_rate_pct: Optional[float] = None
    avg_hold_h: Optional[float] = None
    median_hold_h: Optional[float] = None
    opens_per_day: float = 0.0

class CoinStat(BaseModel):
    coin: str
    volume_usd: float
    pnl_usd: float
    trips: int = 0

class CopyFit(BaseModel):
    value: float                         # 0..100
    parts: Dict[str, float]              # part name -> 0..1 (pre-weight)
    weights: Dict[str, float]
    caps: List[str] = Field(default_factory=list)   # flags that capped it
    cohort_size: int

class TraderScore(BaseModel):            # EXTENDED, all new fields optional for v2 rows
    ...existing fields unchanged...
    sim_copy_capacity_pct: Optional[float] = None
    copy_fit: Optional[CopyFit] = None
    style: Optional[TradingStyle] = None
    last_fill_ms: Optional[int] = None

class TraderRow(BaseModel):              # one Scout board row; what the list route returns
    address: str
    display_name: Optional[str] = None
    account_value_usd: float
    size_tier: SizeTier
    pnl_tier: PnlTier
    style: Optional[TradingStyle] = None
    last_fill_ms: Optional[int] = None
    perf: List[WindowPerf]               # 1d, 7d, 30d, all
    risk_30d: RiskStats
    trades_30d: TradeStats
    top_coins: List[CoinStat] = Field(default_factory=list, max_length=5)
    pnl_spark_30d: List[CurvePoint] = Field(default_factory=list, max_length=60)
    sim_spark_30d: List[CurvePoint] = Field(default_factory=list, max_length=60)
    score: TraderScore                   # sim + Copy Fit at settings_hash
    in_book: bool = False                # filled by api from Settings.leaders
    flags: List[str] = Field(default_factory=list)

class TraderPage(BaseModel):
    as_of_ms: int
    refresh_id: str
    settings_hash: str
    cohort_size: int
    total: int                           # after filters
    rows: List[TraderRow]

class TraderPositionView(BaseModel):
    coin: str
    side: Literal["long", "short"]
    size: float
    notional_usd: float
    entry_px: float
    mark_px: float
    unrealized_pnl_usd: float
    roe_pct: float
    leverage: int
    is_cross: bool
    liquidation_px: Optional[float] = None
    liq_distance_pct: Optional[float] = None
    margin_usd: float
    funding_since_open_usd: float

class RoundTrip(BaseModel):
    coin: str
    side: Literal["long", "short"]
    opened_ms: int
    closed_ms: int
    hold_h: float
    entry_px: float                      # size-weighted avg of opens/adds
    exit_px: float                       # size-weighted avg of reduces/close
    max_notional_usd: float
    net_pnl_usd: float                   # closed_pnl - fees
    win: bool

class AccountRisk(BaseModel):
    perps_usd: float
    spot_usd: float
    staked_usd: float
    account_leverage: float
    margin_usage_pct: float
    nearest_liq_pct: Optional[float] = None
    long_notional_usd: float
    short_notional_usd: float
    long_bias_pct: Optional[float] = None
    unrealized_pnl_usd: float

class TraderProfile(BaseModel):          # the Trader file
    row: TraderRow
    account: AccountRisk
    positions: List[TraderPositionView]
    positions_as_of_ms: int
    pnl_curve: Dict[PnlWindow, List[CurvePoint]]
    value_curve: Dict[PnlWindow, List[CurvePoint]]
    sim_curve: List[CurvePoint]          # hourly, 30d, at settings_hash
    daily_pnl: List[CurvePoint]          # calendar, last 365 days, t = UTC midnight
    risk: List[RiskStats]                # 7d, 30d, all
    trades: List[TradeStats]             # 7d, 30d
    longest_win_streak_days: int
    coins: List[CoinStat]
    recent_trips: List[RoundTrip] = Field(default_factory=list, max_length=100)
    recent_fills: List[LeaderFillView] = Field(default_factory=list, max_length=100)

class LeaderFillView(BaseModel):         # display shape of a leader fill
    time_ms: int; coin: str; side: Literal["B", "A"]; dir: str
    px: float; sz: float; notional_usd: float; closed_pnl_usd: float; fee_usd: float

class WhatIfRequest(BaseModel):
    sim_equity_usd: float = Field(gt=0)
    override: LeaderOverride             # reuses the existing per-leader override shape

class WhatIfResult(BaseModel):
    score: TraderScore                   # sim fields only; copy_fit None (no cohort)
    sim_curve: List[CurvePoint]

class ScoutStatus(BaseModel):
    refresh_id: Optional[str]
    state: Literal["idle", "running", "failed"]
    stage: Optional[Literal["leaderboard", "stats", "sim"]] = None
    done: int = 0
    total: int = 0
    eta_s: Optional[float] = None
    last_ok_ms: Optional[int] = None
    next_due_ms: Optional[int] = None
    error: Optional[str] = None
```

`contracts/venue.py`: add `portfolio(user) -> Optional[Dict[str, Any]]`
(raw HL portfolio: list of `[window, {accountValueHistory, pnlHistory,
vlm}]` for `day, week, month, allTime, perpDay, perpWeek, perpMonth,
perpAllTime`), and `open_orders(user)` for the detail tab. services/hl
implements both; weight 20 each (default). Fakes updated in
`services/discovery/tests/discovery_fakes.py`.

`DiscoveryRun` stays for the existing `/discover` manual runs. Scout uses its
own refresh table so a manual run never blocks the schedule and vice versa.

## 7. Caching plan

Principle: no HL call on the request path for the list. The list is one SQL
query on a precomputed table. The detail page reads a stored profile blob and
does at most one live `clearinghouseState` (weight 2 per dex) when positions
are older than 60 s.

### 7.1 New sqlite tables (data/discovery.db, same WAL file)

```sql
CREATE TABLE scout_universe (          -- stage A output, every leaderboard row kept after filters
  address TEXT PRIMARY KEY, display_name TEXT, account_value REAL,
  pnl_1d REAL, pnl_7d REAL, pnl_30d REAL, pnl_all REAL,
  roi_1d REAL, roi_7d REAL, roi_30d REAL, roi_all REAL,
  vlm_30d REAL, is_vault INTEGER, seen_ms INTEGER);

CREATE TABLE scout_stats (             -- stage B output, per wallet
  address TEXT PRIMARY KEY, updated_ms INTEGER,
  portfolio_json TEXT,                  -- raw portfolio, for curves
  account_json TEXT, positions_json TEXT, positions_ms INTEGER,
  stats_json TEXT);                     -- RiskStats/TradeStats/coins/streak

CREATE TABLE scout_sim (               -- stage C output, per wallet per settings
  address TEXT, settings_hash TEXT, sim_equity REAL, updated_ms INTEGER,
  score_json TEXT, sim_curve_json TEXT,
  PRIMARY KEY (address, settings_hash, sim_equity));

CREATE TABLE scout_rows (              -- denormalised list, rebuilt at end of B or C
  refresh_id TEXT, settings_hash TEXT, address TEXT,
  fit REAL, sim_return REAL, sim_dd REAL,
  account_value REAL, pnl_1d REAL, pnl_7d REAL, pnl_30d REAL, pnl_all REAL,
  roi_1d REAL, roi_7d REAL, roi_30d REAL, roi_all REAL, vlm_30d REAL,
  sharpe REAL, max_dd REAL, win_rate REAL, trips INTEGER,
  style TEXT, size_tier TEXT, last_fill_ms INTEGER,
  top_coin TEXT, hip3_share REAL, coins_csv TEXT, flags_csv TEXT,
  row_json TEXT,                        -- the full TraderRow, served as is
  PRIMARY KEY (refresh_id, settings_hash, address));
CREATE INDEX idx_scout_rows_fit ON scout_rows (refresh_id, settings_hash, fit DESC);
-- plus single-column indexes on the sortable columns used most: pnl_30d, roi_30d, account_value, last_fill_ms

CREATE TABLE scout_refresh (refresh_id TEXT PRIMARY KEY, started_ms INTEGER, finished_ms INTEGER,
  state TEXT, stage TEXT, done INTEGER, total INTEGER, error TEXT);
```

`scout_rows` is written into a new `refresh_id` and the pointer switches only
when the build finishes, so readers never see a half-built list. Keep the
last 3 refreshes, delete older rows.

### 7.2 Schedule (in-process scheduler in discovery, single writer)

| Stage | Every | Work | HL weight |
|---|---|---|---|
| A. universe | 15 min | 1 GET stats-data leaderboard; filter (account value >= $10k, 30d vlm >= $50k, allTime PnL > 0 OR 30d PnL > 0, not vault unless opted in); keep top 300 by 30d PnL; upsert `scout_universe` | 0 |
| B. stats | 60 min, rolling | per wallet: `portfolio` (20), `account_state` (2 x dexes, ~6), incremental `userFillsByTime` (~21 per call when caught up); compute RiskStats, TradeStats, coins, style, positions | ~50 per wallet, ~15k per pass for 300 |
| C. sim + fit | after B, and on settings change | `simulate_wallet` from cached fills, candles from the shared per-coin cache; then Copy Fit over the cohort; build `scout_rows` | candles only for new coins/minutes |
| D. detail live | on page open | positions older than 60 s -> one `account_state`; recent fills older than 30 s -> one incremental fills call | 2 to 30 |

Budget check: 15k weight per B pass at ~720/min available = ~21 min of a
60 min cycle. First backfill is heavier (30d of fills, up to 5 pages of 2000
for an active wallet = ~600 weight): ~40 to 60 min for 300 wallets, once.
Algo wallets past the 10k-fill cap get `fills_truncated` and no further
paging.

Stage B order: stalest first, and wallets in the user's book always first,
so the book is never more than one cycle stale. A wallet that fails twice in
a row is skipped for one cycle and flagged `stale`, never dropped silently.

Progress for B/C is written to `scout_refresh` and, per the repo's
background-job rule, appended to `/tmp/scout-refresh/progress.log` by a
deterministic monitor (`done/total`, rate, ETA from the existing `_eta`).
Read-only job, so no snapshot/diff report.

### 7.3 Serving

- `GET /api/scout/traders`: one SQL query on `scout_rows` for the current
  `(refresh_id, settings_hash)`, returns `row_json` blobs. Target p95 < 50 ms
  for 300 rows on a laptop. `ETag = refresh_id:settings_hash`; web caches
  with SWR keyed on the query string.
- If no rows exist for the current `settings_hash` yet (settings just
  changed), serve the previous hash's rows with `stale_settings: true` and
  kick stage C. Never block the page on a sim.
- Profile: `scout_stats` + `scout_sim` assembled into `TraderProfile`; an
  address not in the universe gets an on-demand stage B + C for that one
  wallet (rate-limited to 1 concurrent), returned when done or 202 + poll.

## 8. API routes (services/api, all behind `require_auth`)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/scout/traders` | `TraderPage` | filters/sorts in section 5; `in_book` filled from Settings |
| GET | `/api/scout/traders/{address}` | `TraderProfile` | 404 if invalid address; 202 + `ScoutStatus` if being built |
| GET | `/api/scout/traders/{address}/fills?before_ms=&limit=` | `List[LeaderFillView]` | paged from the fills cache |
| GET | `/api/scout/traders/{address}/orders` | open orders | live, weight 20, cached 30 s |
| POST | `/api/scout/traders/{address}/what-if` | `WhatIfResult` | body `WhatIfRequest`; cached fills and candles only; 1 concurrent |
| GET | `/api/scout/presets` | coin chips + hip3 count | from current `scout_rows` |
| GET | `/api/scout/status` | `ScoutStatus` | for the refresh badge |
| POST | `/api/scout/refresh` | `ScoutStatus` | 409 if running |
| existing POST | `/api/leaders` | `Settings` | Add to book |
| existing PATCH | `/api/settings` | `Settings` | save what-if as `LeaderOverride` |

Api talks to discovery only through `discovery.public` (add
`scout_page(query)`, `scout_profile(address)`, `scout_what_if(...)`,
`scout_status()`, `scout_refresh()`), same pattern as `discovery_client.py`.
Regenerate `services/api/openapi.json` and web types.

## 9. Gaps vs their copy flow (Settings contract, separate change)

1. **Asset allow/deny list**: `Settings.coin_allow: List[str]`,
   `Settings.coin_deny: List[str]`, per-leader in `LeaderOverride`. Engine
   skips with reason `coin_filtered`. Sim honours it.
2. **Counter-trade**: `LeaderOverride.invert: bool`. Engine flips side.
   Higher risk; ship behind `dry_run` first. Sim supports it, so the trader
   file can show "inverse copy" return honestly.
3. **Weights across leaders**: proportional mode already uses `sleeve_frac`
   split equally; add `LeaderOverride.weight` (default 1) so the split is
   weighted.

Out of scope for v1, listed so nobody assumes them done.

## 10. Tests, evals, measurable outcome

Gate tests (discovery, all offline with fakes, < 2 s):
- `test_portfolio_stats.py`: daily resample, drawdown on a known series
  (e.g. +10%, -20%, +5% -> 20.0%), sharpe/sortino with hand-computed values,
  null on < 7 days, AV < 100 days skipped, streak scan.
- `test_round_trips.py`: flip splits into two trips, partial closes
  aggregate into one trip, trips crossing the window edge excluded, win on
  net of fees.
- `test_style.py`: thresholds at each boundary.
- `test_copy_fit.py`: weights sum to 1; percentile ties; each gate and cap;
  liquidated never above 20; a steady trader outranks a higher-PnL
  liquidated one (mirrors existing scoring test); deterministic for a fixed
  cohort.
- `test_scout_db.py`: atomic refresh pointer, readers never see a partial
  build, retention of 3 refreshes.
- api: route param validation, ETag, `in_book`, 409 on concurrent refresh.
- web (vitest): filter-to-query mapping, `$`/`%` toggle, sparkline with
  negative segments, phone card layout.

Periodic evals (live HL, read only, before ship and nightly):
- `eval_scout_live.py`: stage A+B on 20 wallets; every row has all fields
  or an explicit flag; our 30d PnL from portfolio matches the leaderboard
  month PnL within 2% for >= 90% of wallets (sanity of the portfolio parse).
- `eval_copy_fit_forward.py`: the measurable outcome. Freeze Copy Fit at
  T, run the sim for T..T+7d, compare top-decile vs bottom-decile forward
  sim return. Pass threshold: top decile beats bottom decile and beats
  "rank by 30d PnL" top decile in >= 3 of the last 4 weekly snapshots.
  This is what tunes the weights in section 3.

Outcome the page moves: time from "I want a new leader" to "leader in book
with sane settings", and the forward sim return of leaders added from Scout
vs leaders added by hand. Trace: log line `scout.add_to_book address fit
rank refresh_id` on every Add to book, so the forward eval can join on it.
