# What real users expect from a Hyperliquid copy-trading product

2026-10-14. Research only, no code changed. Goal: ground a QA/upgrade pass on
copycat (Scout leaderboard, Trader file, invest ticket, portfolio,
account/funding, Claude Code MCP) in what Hyperdash shows, what Hyperliquid's
own app assumes, and what real copiers actually complain about. Read-only web
research (WebSearch/WebFetch) plus a read of copycat's own prior research
(`docs/research/copytrading_page_spec.md`, `docs/research/W-CC1_*`) and the
already-shipped Scout/thesis code (`services/discovery/discovery/scout/`,
`services/discovery/discovery/thesis/`, `services/mcp/copycat_mcp/`).

Where a claim comes from copycat's own code or prior research, it is cited by
file path, not URL. Everything else is cited by URL in Sources. A few points
are my own inference from the sources, not a direct quote; those are marked
**(inference)**.

## Executive summary

1. Every credible leaderboard shows PnL/ROI across multiple windows (day,
   week, month, all-time), never one cherry-picked window. Scout's `TraderRow`
   already carries all four; keep it that way.
2. Hyperliquid's own definition is specific and copycat must match it exactly:
   account value includes unrealized PnL and vault balances; PnL is account
   value plus net deposits minus withdrawals, i.e. deposits are explicitly
   excluded from trading PnL.
3. The single biggest documented failure mode is proportional sizing on a
   smaller account: a 90-day, 100k-outcome study found 97% of leaders profitable
   but only ~44% of their copiers were. Sizing math at the copier's own equity,
   shown before copying, is the product's main job.
4. Algorithmic/market-maker wallets and fast coattail-riders (wallets that
   re-enter another top wallet's position seconds to minutes later) dominate
   raw-PnL leaderboards and cannot be meaningfully copied by a retail account.
   Hyperdash already warns on "algo" tag; copycat's `hft` cap does the same
   but has no coattail detector yet.
5. Leaderboards suffer survivorship bias by construction: wallets that blow up
   stop being shown as "current" top performers. Hyperliquid's own top
   wallets (James Wynn, Andrew Tate, and others named in a widely shared
   "all 8 wiped out" thread) are the concrete, on-platform version of this.
6. Hyperliquid's $10 minimum order size is a hard floor that silently skips
   small copies; copycat's own W-CC1 research already found a $1.29 test
   account can't clear it. This must be shown as a pre-copy number
   ("you can execute N% of his opens at this size"), not discovered after.
7. A trustworthy trade history must net fees into realized PnL (copycat does:
   `net_pnl_usd = closed_pnl - fee` in `trips.py`) but copycat's trip PnL does
   **not** currently net funding paid or earned during the hold. Trading-journal
   sources put the funding effect on net R at 20-40% for holds over 8 hours.
   This is the single clearest gap found in this research.
8. A good written thesis, by both fund-letter and trading-journal convention,
   states a falsifiable edge, ties position size to conviction, and states
   what would change the view (kill criteria), not just a list of caveats at
   the end. Copycat's `write_thesis` prompt already requires 8 sections close
   to this; it is missing an explicit "what would make me wrong" section.
9. Vault depositors on Hyperliquid accept a real lockup (1 day user vaults, 4
   days HLP) and a 10% profit share with 5% leader skin-in-game. A copycat
   "Add to book" on a vault address must not be confused with this: it has
   none of those terms, it's a simulated proportional copy.
10. Copy trading scam literature's top red flag is hidden unrealized losses
    shown only as realized stats. copycat is read-only against public HL data
    with no custody, so the scam vector doesn't apply directly, but the
    underlying lesson holds: always show the leader's live unrealized PnL and
    open risk next to the win-rate stat, never one without the other.

## Non-negotiables

| Expectation | Evidence | What it implies for copycat |
|---|---|---|
| Multiple PnL/ROI windows (1d/7d/30d/all), not one | HL leaderboard shows day/week/month/all-time PnL, ROI, volume ([Apify HL leaderboard scraper docs](https://apify.com/gochujang/hyperliquid-leaderboard.md)); Hyperdash explore adds a 1d/7d/30d/all window on top of its default 7d (`docs/research/copytrading_page_spec.md` section 0.3, read from the live page) | Scout's `TraderRow.perf: List[WindowPerf]` already carries all four (`docs/research/copytrading_page_spec.md` section 6). Keep all four live in v1, don't quietly ship 30d-only. |
| Account value = equity incl. unrealized PnL + vault balances; PnL excludes deposits | Hyperliquid docs, quoted directly: "Account Value ... includes unrealized pnl from cross and isolated margin positions, as well as vault balances"; "PnL is defined as account value plus net deposits, i.e. account value + deposits - withdrawals" ([Hyperliquid docs, portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)) | Matches copycat's own stated caveat that `pnlHistory` excludes deposits/withdrawals but `accountValueHistory` doesn't, so the value chart must be labeled "account value," never "performance" (`docs/research/copytrading_page_spec.md` section 2, caveats). Hold this line in the UI copy. |
| Portfolio graphs are explicitly not precision-grade | HL docs: graphs "are samples on deposits and withdrawals and also every 15 minutes" and are "not recommended [for] precise accounting purposes, as the interpolation between samples may not reflect the actual change in unrealized pnl" ([Hyperliquid docs, portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)) | Copycat's own sim curve is built hourly from candles (`sim_curve: List[CurvePoint]`, `docs/research/copytrading_page_spec.md` section 6), which is a real precision edge over HL's own 15-min sampling. State that edge explicitly in the UI instead of leaving it implicit. |
| Minimum order size is a hard floor that breaks small-account copying | HL enforces a $10 minimum notional per order (exception: exact reduce-only close); copy bots widely document "small fills will be skipped when the proportional size falls below $10" ([buildix.trade min order size guide](https://www.buildix.trade/blog/hyperliquid-minimum-order-size-all-pairs-leverage-limits-2026); general copy-bot docs found in search) | Already validated on copycat's own account: a $1.29 test wallet can't clear the $10.50 effective floor against any of 10 real leaders (`docs/research/W-CC1_copycat_leaders.md`). `copy_capacity` (share of a leader's opens executable at the user's size) must be shown before "Add to book," not just in an expandable row (`docs/research/copytrading_page_spec.md` section 2, metric 32). |
| Proportional copy sizing can ruin an account the leader survives fine | 90-day, 100k-outcome study across exchanges: 97% of leaders were profitable but only ~44% of copiers were; documented case of a 73%-win-rate wallet copier down 18% in 3 weeks while the leader stayed fine, because the whale's $2M position was 4% of his book and a much larger share of the copier's ([Bitsgap, "Whale Copy-Trading: Visible Doesn't Mean Repeatable"](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires)) | Copycat already runs a what-if sim at the user's own equity before saving (`WhatIfResult`, `docs/research/copytrading_page_spec.md` section 6), which is the right instinct. It must be the thing shown first, not a secondary panel, and the sim's own max drawdown at the user's size (not the leader's) is the number that matters. |
| Algo/market-maker wallets must be flagged, not ranked as ordinary skill | Hyperdash's own in-app warning: copying a trader tagged "algorithmic" "may not replicate their results due to execution speed differences" ([Hyperdash copy-trade docs](https://docs.hyperdash.com/copy-trade)); separately, a chunk of near-top HL leaderboard wallets are documented coattail-riders that "enter identical positions seconds to minutes after" a top-10 wallet and aren't independently skilled ([coinmarketman, "The Wallets Copying Hyperliquid's Top 10"](https://coinmarketman.com/blog/the-wallets-copying-hyperliquids-top-10-and-how-to-spot-them--en/)) | Copycat's `style=algo` / `hft` flag already caps Copy Fit at 50 (`services/discovery/discovery/scout/copy_fit.py`, `CAP_HFT = 50.0`). There is no detector yet for a wallet whose entries consistently lag another top wallet by seconds on the same coin/side; that's a real, currently-unflagged case (P1 below). |
| Leaderboards must not quietly disappear failed wallets | Formal argument for survivorship bias in public trader rankings, plus a worked simulation showing published "top trader" returns can reach +24.6% average by year five from pure survival filtering with zero true skill ([NakedPnL, survivorship bias guide](https://www.nakedpnl.com/guides/survivorship-bias-trader-rankings)); concretely on Hyperliquid, widely covered top-leaderboard names who later blew up: James Wynn, liquidated nine times, down ~$22M on one wallet ([DL News](https://www.dlnews.com/articles/defi/hyperliquid-trader-james-wynn-liquidated-nine-times/)); Andrew Tate, $727K wiped out after a 25x ETH long liquidation ([CryptoSlate](https://cryptoslate.com/inside-andrew-tates-total-crypto-liquidation-meltdown-from-leverage-trading/)); a widely shared on-chain summary of 8 once-huge-profit HL wallets that "ended up getting wiped out" ([Lookonchain on X](https://x.com/lookonchain/status/2017885115859505623)) | Copycat's `liquidated` flag already caps Copy Fit at 20 once it sees `sim_liquidations > 0` (`services/discovery/discovery/scout/copy_fit.py`), which is the right reaction to a wallet that has already blown up. There is no tracking yet of wallets that simply drop out of the ranked universe (fall below the top-300 cutoff) without having liquidated; those silently vanish today rather than leaving a "no longer ranked" record (P1 below). |
| Vault terms (lockup, profit share, skin-in-game) are not the same as a copy | HL vault docs: "10% profit share to the leader," "HLP has a lock-up period of 4 days. User vaults have a lock-up period of 1 day," leader must keep "5% of the vault's equity" as skin in the game ([Hyperliquid docs, for vault depositors](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/for-vault-depositors); fee/skin-in-game figures corroborated by [eco.com vault strategies guide](https://eco.com/support/en/articles/15197987-hyperliquid-vault-strategies-2026-hlp-and-user-vaults-explained)) | Copycat's `vault` flag already caps Copy Fit at 50 (`services/discovery/discovery/scout/copy_fit.py`). It should also surface the real HL terms (lockup days, 10% profit share) on the Trader file whenever the address is a vault, so "Add to book" (instant, fee-free sim copy) is never mistaken for an actual HL vault deposit. |
| Fees and funding must net into realized PnL, not just price moves | For perpetuals specifically, ignoring funding and liquidation distance "can misrepresent your net R by 20-40% on any hold lasting longer than 8 hours" **(inference from aggregated search synthesis, not a single quoted primary source: treat the exact 20-40% figure as directional, not exact)** | Copycat already nets fees (`net_pnl_usd = cur["pnl"] - cur["fee"]`, `services/discovery/discovery/thesis/trips.py:94`, same in `contracts/models.py RoundTrip.net_pnl_usd`). It does **not** net funding accrued during the hold into that figure. Funding is tracked separately per-fill endpoint (`userFunding`, `docs/research/copytrading_page_spec.md` section 2, metric 34, "on demand") but never joined into the round trip. This is the clearest concrete gap in this research (P0 below). |
| A thesis must be falsifiable and state what would break it | "An investment thesis is a written, falsifiable argument... a thesis that cannot be wrong is not a thesis"; "sizing belongs inside the thesis, a thesis that never influences position size is only an opinion"; kill criteria/invalidation should be written before the fact, tied to events not daily price noise ([growthequityinterviewguide.com, investment thesis framework](https://growthequityinterviewguide.com/venture-capital/venture-capital-industry/investment-thesis); [kubera.com, investment thesis](https://www.kubera.com/blog/investment-thesis)) | Copycat's `write_thesis` prompt already requires "Confidence & caveats" as its own section, hedges under ~30 trips, and requires sizing/leverage numbers in "Sizing & risk" (`services/mcp/copycat_mcp/prompts.py`). It does not explicitly ask for a stated "what would change my mind / kill criteria" line distinct from a caveat; see Thesis rubric criterion 9 and P1 below. |

## Known ways copiers lose money

| Failure | Evidence | The product guard that prevents it |
|---|---|---|
| Latency/slippage: copier fills seconds to minutes after the leader, at a worse price | Binance futures caps opening slippage at 0.5% BTC/ETH, 1.5% others, with no cap on closing; Bybit's copy service defaults to 0.1% max slippage (adjustable to 5%); "by the time copiers see and execute, price and funding have shifted" (aggregated from [Bitsgap](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires) and copy-trading exchange comparisons found in search) | `LeaderOverride.max_worse_entry_pct` (Hyperdash's own default is 10%, max 50%, per `docs/research/copytrading_page_spec.md` section 0.4) already skips an open if price has moved past the allowed deviation from the leader's own entry. |
| Proportional sizing on a much smaller account turns a survivable drawdown into a liquidation | 90-day study: 97% of leaders green, only ~44% of copiers profitable; a documented 73%-win-rate wallet whose copier was down 18% in 3 weeks ([Bitsgap](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires)) | Copycat's what-if sim (`WhatIfResult.sim_curve`, `docs/research/copytrading_page_spec.md` section 6) runs the leader's actual historical fills against the user's own equity and settings before saving, surfacing sim max drawdown at the user's size, not the leader's. |
| Minimum order size causes selective skips that change the leader's real risk shape (small hedges/scale-outs get skipped, big directional opens don't) | HL's $10 minimum notional per order is a hard floor; copy bots document skipped fills below it ([buildix.trade](https://www.buildix.trade/blog/hyperliquid-minimum-order-size-all-pairs-leverage-limits-2026)); confirmed directly on a real test account (`docs/research/W-CC1_copycat_leaders.md`, $1.29 equity, 10 real leaders, none clear the floor) | `copy_capacity` (share of the leader's opens the sim could actually execute, `docs/research/copytrading_page_spec.md` section 2, metric 32) must be shown pre-copy, not buried in an expand row. |
| Leverage mismatch changes the liquidation distance the copier actually has, independent of the leader's own risk | "If a master trader changes leverage from 30x to 10x, a follower's leverage may remain at 30x if their available balance isn't enough" (aggregated from copy-trading leverage-mismatch sources found in search, incl. [OneKey, Copy Trading on Hyperliquid](https://onekey.so/blog/ecosystem/copy-trading-on-hyperliquid/)) | `max_position_leverage` (1-40x, default 20x per Hyperdash's own default, `docs/research/copytrading_page_spec.md` section 0.4) caps the copier's own leverage regardless of the leader's; Trader file shows `nearest_liq_pct` / distance-to-liquidation (`docs/research/copytrading_page_spec.md` section 2, metric 26) computed at the copier's own setting. |
| Algo/market-maker/coattail wallets look skilled on raw PnL but can't be followed at any retail latency | Hyperdash's own algo warning ([docs.hyperdash.com/copy-trade](https://docs.hyperdash.com/copy-trade)); documented coattail-riders on the HL leaderboard that enter "seconds to minutes after" a top-10 wallet ([coinmarketman](https://coinmarketman.com/blog/the-wallets-copying-hyperliquids-top-10-and-how-to-spot-them--en/)) | `style=algo`/`hft` caps Copy Fit at 50 (`services/discovery/discovery/scout/copy_fit.py`, `CAP_HFT`). No detector yet for the coattail case specifically (P1 below). |
| Leaderboard survivorship bias: the ranking never shows who already blew up | Simulation showing +24.6% average "skill" from pure survival filtering by year five with zero true edge ([NakedPnL](https://www.nakedpnl.com/guides/survivorship-bias-trader-rankings)); on-platform cases: James Wynn ([DL News](https://www.dlnews.com/articles/defi/hyperliquid-trader-james-wynn-liquidated-nine-times/)), Andrew Tate ([CryptoSlate](https://cryptoslate.com/inside-andrew-tates-total-crypto-liquidation-meltdown-from-leverage-trading/)), 8 wiped HL wallets ([Lookonchain on X](https://x.com/lookonchain/status/2017885115859505623)) | `liquidated` caps Copy Fit at 20 once `sim_liquidations > 0` is observed (`services/discovery/discovery/scout/copy_fit.py`). Gap: wallets that drop below the top-300 cutoff without liquidating simply disappear from `scout_universe` with no "previously ranked" trail (P1 below). |
| PnL figure conflated with account value, making deposits look like trading skill | HL's own docs make the distinction explicit: PnL excludes deposits/withdrawals, account value doesn't ([HL docs, portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)) | Copycat's own caveat already states this and commits to never labeling the account-value chart "performance" (`docs/research/copytrading_page_spec.md` section 2, caveats). Must be enforced at the UI copy layer, not just the data layer. |
| Vault depositor confuses a copy-sim with a real HL vault (lockup, profit share) | HL vault terms: 1-day (user vault) / 4-day (HLP) lockup, 10% profit share, 5% leader skin-in-game ([HL docs, for vault depositors](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/for-vault-depositors)) | `vault` flag caps Copy Fit at 50 (`services/discovery/discovery/scout/copy_fit.py`, `CAP_VAULT`). Gap: the real lockup/fee terms are not yet surfaced on the Trader file for a vault address (P1 below). |
| Round-trip PnL understates true cost on longer holds because funding isn't netted in | Funding-effect-on-net-R finding from aggregated trading-journal search (directional, not a single primary citation, see non-negotiables table note) | None yet. `net_pnl_usd = cur["pnl"] - cur["fee"]` in `services/discovery/discovery/thesis/trips.py:94` (same shape in `contracts/models.py RoundTrip`) has no funding term, confirmed by reading the file. This is the clearest gap found (P0 below). |
| Hidden unrealized losses presented only via realized/closed stats | Copy-trading scam literature's top red flag: "examine unrealized (floating) profits and losses... positions held for weeks or months at a loss are red flags" ([copi-tools.com, copy trading scam red flags](https://copi-tools.com/blog/copytrade-scam/)) | Copycat has no custody and is read-only against public HL data, so the scam vector itself doesn't apply, but the Trader file already shows unrealized PnL / open positions as top tiles alongside win rate (`docs/research/copytrading_page_spec.md` section 0.4), which is the correct shape; keep both always visible together, never one without the other. |

## Leaderboard trust checklist

- Shows PnL, ROI, **and** account value together, never PnL or ROI alone (a
  $50 account up 400% reads identically to a $5M account up 400% in percent
  terms alone).
- Multiple time windows available (1d/7d/30d/all), with the active window
  always labeled on screen.
- Style/activity classification (algo, scalp, intraday, swing, position) so a
  market-maker or HFT wallet is visually distinct from a discretionary trader.
- A minimum sample size (trips, days active) before a score is trusted;
  "too few trades" shown as an explicit cap, not a silently high score.
- A wallet's own liquidation/blowup history is visible on its row, not just
  implied by a capped score.
- The scoring formula is published with a per-part breakdown, never an
  opaque single number.
- "Last active" freshness is shown; stale or inactive wallets are flagged or
  dropped, not left ranked on old data.
- Vaults are labeled distinctly from individual wallets, with their real
  lockup and fee terms, not folded into the same row shape.
- The score reflects the viewer's own account size and settings (a sim term),
  not a one-size-fits-all number computed only from the leader's own stats.
- States plainly what cannot be verified from public fills alone: hedges on
  another venue, wash trading, backfilled history.

## Trade history correctness checklist

- Round trips are reconstructed flat-to-flat per coin; a flip (long to short
  with no flat in between) is split into a close and a separate open, never
  counted as one trip.
- Partial fills, adds, and scale-outs aggregate into one trip; a trip is
  never shown as several disconnected trades because the leader entered or
  exited in pieces.
- Realized PnL nets fees. It should also net funding accrued during the hold
  for perpetuals; today it does not (see P0 below).
- Unrealized PnL on still-open positions is shown separately from realized
  PnL and never folded into a win-rate count while still open.
- All timestamps are UTC, and any "month" or "30d" window is labeled as
  whatever bucket the data source actually uses, not assumed to be a strict
  trailing period (HL's own leaderboard "month" is a bucket, not a strict
  trailing 30 days).
- Deposits and withdrawals are excluded from the PnL/performance curve and
  included in the account-value curve, and the two are never shown with the
  same label.
- Data truncation (e.g., a fill-history API cap) is disclosed as a flag on
  the affected rows, not silently absorbed into a smaller-looking number.
- Trips still open at the end of the measurement window are excluded from
  hold-time and win-rate stats, not counted as a win because they are
  currently in profit.
- A liquidation is shown as its own distinct event type in the trade
  history, not folded into an ordinary closed loss.

## Thesis quality rubric

Score 0-2 per criterion (0 = absent/fails, 1 = present but weak, 2 = clearly
meets the bar). For an LLM eval, run this against the markdown body of a
saved `Thesis` (the `ta` or `claude_code` source) and require the sections
copycat already mandates (`services/mcp/copycat_mcp/prompts.py`,
`THESIS_SECTIONS`) to exist before scoring content.

| # | Criterion | 0 | 1 | 2 |
|---|---|---|---|---|
| 1 | Edge stated as one falsifiable sentence | Missing, or generic ("good trader") | Present but vague or spans multiple sentences | One sentence, specific, states the claimed source of returns in a way a reader could check against the evidence |
| 2 | Entry behavior backed by cited evidence, not assertion | No supporting numbers or trade citations | Numbers given but no specific trades cited | Fingerprint percentages AND specific trades cited by coin, side, UTC date |
| 3 | Sizing and risk quantified | No leverage/sizing numbers | Some numbers (e.g. avg leverage only) | Avg and max leverage, worst trip as % of equity, and concentration all stated |
| 4 | Exit behavior quantified | Not discussed | Described qualitatively | Loser-hold-vs-winner-hold ratio and payoff ratio both stated with numbers |
| 5 | Timing/activity disclosed | Not discussed | Vague ("active often") | UTC hours/weekdays and opens-per-day or activity level stated |
| 6 | Copier-specific risk addressed | Not discussed | Generic risk warning | Names at least two of: min-order-size fit at a stated account size, liquidation distance at the copier's own leverage, latency sensitivity for short holds/breakout entries |
| 7 | "What to learn" is concrete and practicable | Platitude ("be disciplined") | One concrete habit | Multiple concrete, checkable habits a reader could paper-trade |
| 8 | Confidence hedged to sample size | No sample size stated | Sample size stated, no hedge on claims | Sample size (trips, window) stated up front and every pattern claim hedged when the count is small (copycat's own prompt puts this at ~30 round trips) |
| 9 | States what would change the view (kill criteria) | Absent | Folded vaguely into caveats | A specific, separate statement of what evidence would invalidate the thesis or change the reader's mind |
| 10 | No financial-advice framing | Tells the reader to buy/copy/size up | Mostly descriptive, one imperative slip | Purely descriptive throughout, no "you should" |
| 11 | Numbers traceable to tool output | Numbers appear uncited/invented | Mostly traceable, one unsupported figure | Every number in the thesis can be matched to a tool call result (fingerprint, profile, trades, candles) |
| 12 | Format discipline | Missing required sections or over length | All sections present, minor style slips (em dashes, inconsistent dates) | All 8 required `##` sections present in order, under 20,000 characters, no em dashes |

Max 24. Suggested pass bar: 18/24 with no criterion scoring 0, since a single
0 (e.g. an invented number, or advice framing) is disqualifying regardless of
total.

## Prioritized asks for copycat

**P0**

1. Net funding accrued during the hold into round-trip PnL
   (`services/discovery/discovery/thesis/trips.py:94`,
   `contracts/models.py RoundTrip.net_pnl_usd`), so a multi-hour hold's
   win/loss isn't misstated by the funding it paid or earned.
2. Show `copy_capacity` and the what-if sim's max drawdown at my own equity
   on the main Trader file panel before "Add to book," not only in an
   expandable row, so I see "this plan skips 40% of his opens at your size"
   before I commit.
3. Show a leader's liquidation/blowup history in plain language directly on
   the Scout board row (e.g. "liquidated 2x in the sim window"), not only as
   a decoded Copy Fit cap, so I don't have to reverse-engineer a score to
   know someone already blew up.
4. Warn me, before I confirm, whenever my chosen leverage gives me a tighter
   liquidation distance than the leader's own effective leverage, since
   that's the most common documented way a copier gets liquidated on a trade
   the leader survives.

**P1**

5. Label a vault address distinctly on the Trader file with its real HL
   terms (lockup days, 10% profit share, 5% leader skin-in-game), so I never
   mistake "Add to book" for an actual HL vault deposit.
6. Add a coattail-rider check (a wallet whose entries consistently lag
   another top-ranked wallet by seconds to minutes on the same coin and
   side), so a fast copy-of-a-copy wallet doesn't rank as independently
   skilled.
7. Keep a record when a wallet drops out of the ranked top-300 universe
   (not just when it liquidates): "no longer ranked, last seen at $X on
   date Y," so a wallet can't quietly vanish instead of being shown as a
   faded performer.
8. Add an explicit "what would change this view" line to both the
   deterministic TA thesis and the `write_thesis` MCP prompt
   (`services/mcp/copycat_mcp/prompts.py`), separate from the existing
   caveats list, so invalidation isn't an afterthought bullet.

**P2**

9. Show a small rank-or-Fit trajectory sparkline on the Trader file so a
   one-off lucky month is visually distinguishable from sustained
   performance.
10. Ship the asset allow/deny list and counter-trade mode already scoped in
    the Scout spec (`docs/research/copytrading_page_spec.md` section 9),
    since Hyperdash users already expect both from the reference product.
11. Publish a one-paragraph "what we can't verify" note next to Copy Fit
    (wash trading, off-exchange hedges, backfilled history), matching the
    disclosure standard a careful leaderboard holds itself to.

## Sources

- [Hyperliquid docs, portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs): account value, PnL, ROI definitions, 15-min sampling caveat
- [Hyperliquid docs, for vault depositors](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/for-vault-depositors): lockups, profit share, leader skin-in-game
- [Hyperdash copy-trade docs](https://docs.hyperdash.com/copy-trade): copy settings table, algo warning, min funding, builder fee
- [Hyperdash learn: best tools for trading Hyperliquid](https://hyperdash.com/learn/best-tools-trading-hyperliquid)
- [Bankless: getting started with Hyperdash's revamped trading terminal](https://www.bankless.com/read/getting-started-with-hyperdashs-revamped-trading-terminal)
- [HyperMirror vs HyperDash comparison](https://hypermirror.io/compare/hypermirror-vs-hyperdash)
- [ShieldTX: Hyperbot, Dexly & HyperDash, are they copying your trades?](https://www.shieldtx.xyz/blog/hyperbot-dexly-hyperdash-copy-trading-tools)
- [Apify: Hyperliquid Top Traders Leaderboard actor docs](https://apify.com/gochujang/hyperliquid-leaderboard.md): leaderboard column shape
- [NakedPnL: survivorship bias in public trader rankings](https://www.nakedpnl.com/guides/survivorship-bias-trader-rankings)
- [Bitsgap: Whale Copy-Trading, Visible Doesn't Mean Repeatable](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires): 90-day/100k-outcome study, specific backfire case
- [coinmarketman: the wallets copying Hyperliquid's top 10](https://coinmarketman.com/blog/the-wallets-copying-hyperliquids-top-10-and-how-to-spot-them--en/): coattail-riders
- [coinmarketman: copy trading on Hyperliquid, how to find and follow smart wallets](https://coinmarketman.com/blog/copy-trading-on-hyperliquid-how-to-find-and-follow-smart-wallets--en/)
- [DL News: Hyperliquid trader James Wynn liquidated nine times](https://www.dlnews.com/articles/defi/hyperliquid-trader-james-wynn-liquidated-nine-times/)
- [CryptoSlate: inside Andrew Tate's total crypto liquidation meltdown](https://cryptoslate.com/inside-andrew-tates-total-crypto-liquidation-meltdown-from-leverage-trading/)
- [Lookonchain on X: 8 Hyperliquid traders once huge, all wiped out](https://x.com/lookonchain/status/2017885115859505623)
- [WisdomTree Prime: the great whale slap, HLP vault loss](https://www.wisdomtreeprime.com/blog/the-great-whale-slap-how-a-whale-offloaded-4m-in-losses-to-hyperliquids-hlp-vault/)
- [copi-tools.com: copy trading scam red flags](https://copi-tools.com/blog/copytrade-scam/)
- [OneKey: copy trading on Hyperliquid, a practical guide](https://onekey.so/blog/ecosystem/copy-trading-on-hyperliquid/)
- [OneKey: Hyperliquid vault deposit mechanism explained](https://onekey.so/blog/ecosystem/hyperliquid-vault-deposit-guide/)
- [eco.com: Hyperliquid vault strategies, HLP and user vaults explained](https://eco.com/support/en/articles/15197987-hyperliquid-vault-strategies-2026-hlp-and-user-vaults-explained)
- [buildix.trade: Hyperliquid minimum order size for every pair](https://www.buildix.trade/blog/hyperliquid-minimum-order-size-all-pairs-leverage-limits-2026)
- [TradeZella: the complete guide to crypto trading journals](https://www.tradezella.com/blog/crypto-trading-journal)
- [TradeZella: the complete guide to trading journals](https://www.tradezella.com/blog/trading-journal-guide)
- [Blofin academy: trading journal and review](https://blofin.com/academy/education/trading/post-trade-journal)
- [Gainium: trade journal help docs](https://gainium.io/help/trade-journal)
- [growthequityinterviewguide.com: investment thesis framework](https://growthequityinterviewguide.com/venture-capital/venture-capital-industry/investment-thesis)
- [Kubera: investment thesis](https://www.kubera.com/blog/investment-thesis)
- [Roger Montgomery: on position sizing and hedge funds](https://rogermontgomery.com/on-position-sizing-and-hedge-funds/)
- [Aleph Blog: on position sizing in equity long-short hedge funds](https://alephblog.com/?p=7001)

Internal sources (copycat's own prior research and shipped code, read for this doc, not re-cited by URL):

- `docs/research/copytrading_page_spec.md`: the full capture and spec of Hyperdash's copytrading/explore pages and copycat's Scout design
- `docs/research/W-CC1_copycat_leaders.md`, `W-CC1_leader_profile.py`, `W-CC1_results.json`: real-account sizing viability math against 10 leaderboard wallets
- `services/discovery/discovery/scout/copy_fit.py`: Copy Fit gates/caps (liquidated, too_few_trades, hft, vault)
- `services/discovery/discovery/thesis/trips.py`, `template.py`, `README.md`: round-trip reconstruction, fingerprint, and the deterministic TA thesis template
- `services/mcp/copycat_mcp/prompts.py`, `services/mcp/claude/commands/copycat-thesis.md`: the `write_thesis` and `copy_trader` MCP prompts and their required sections
- `contracts/models.py`: `RoundTrip`, `TraderRow`, `WhatIfResult`, `CopyFit` contract shapes
