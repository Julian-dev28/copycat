# copycat UX audit

Date: 2026-10-05. App: `services/web` at http://localhost:3000 (real api at :8787, live trading on, one real ETH copy open), plus `?demo=1`, `&acct=small`, `&acct=large`. Viewports: 1456x835 desktop, 390px (rendered in a 390px iframe). Companion: [DESIGN.md](./DESIGN.md).

**Rules followed:** in the real app, look only. No Copy, Update, Stop, Pause, Halt, Close all, Enable, Dry run, sliders, inputs, or wallet-manager actions. The only real-app interactions were clicking the Strategy tab on a trader page, opening the Wallets dialog (Trading accounts) and closing it with Escape. All interactive flows (typing amounts, pressing Copy wallet) were done in `?demo=1`, whose Trade source is in-memory (`src/lib/trade/source.ts` `demoTrade`). Working tree note: other sessions were editing `services/web` during this audit (a Scout "Leaderboard / Custom sim" sub-nav appeared via `src/components/scoutNav.ts`), so some findings may already be moving.

Severity: **blocker** = can lose money or mislead about money now. **high** = wrong or contradicting numbers, or a core flow is confusing. **medium** = friction, jargon, layout. **low** = polish.

---

## Top 10

| # | Sev | Finding | Fix |
|---|---|---|---|
| 1 | blocker | **Demo mode leaks into the real app.** The nav carries `?demo=1` to `/settings` and `/discover`, but neither page reads demo mode: `src/app/settings/page.tsx` always uses `useSettings()` / `usePatchSettings()` against the real api, and `discover` has no demo branch. In demo, Settings shows the operator's live values ("Trading enabled" on, Equity sleeve 19%) with no demo banner, and every toggle, slider and Discover "Copy" button would change the live account. The demo Trade banner even says "Turn it off in Settings" | Give Settings and Discover a demo source (like `demoTrade`), or render a read-only "Settings are not available in demo" panel. Show the demo strip on every route. Gate test: with `?demo=1`, no PATCH or POST reaches `apiFetch` |
| 2 | blocker | **Day P&L counts the deposit.** Portfolio shows `Day P&L +$24.44` on a $24.57 account, while the copies show uPnL -$0.02 / realized -$0.01 and Account shows all-time PnL -$444.21. `EngineStatusBar.tsx:33` renders `status.day_pnl_usd` as-is; the engine seems to measure today's equity against a start-of-day value taken before funds arrived | Engine: compute day PnL net of transfers (equity delta minus net deposits/withdrawals since 00:00 UTC). Web: label it "Day P&L (UTC)" and hide it when the engine flags transfers it could not net out. Regression test with a deposit mid-day |
| 3 | high | **Leverage shown is not leverage used.** Trade's "Your wallets" says 0xa38f…dccf runs at **50x** and 0x0c4a…1b19 at **25x**; the real ETH copy opened at **15x iso**, and Trade's own preview shows BTC copy at 15x under "Set leverage 25x". Cause: Settings > Copy behavior "Maximum position leverage 15x" silently caps every copy. Settings > Leaders also prints "· 15x" for both leaders, ignoring their per-wallet terms (`LeaderRow.tsx:21` uses global settings only). Three different numbers for one thing | Ticket: clamp the slider to `max_position_leverage` and show "capped at 15x by Settings" inline. Wallet tables: show effective leverage ("50x → 15x cap"). LeaderRow: show the wallet's own terms. (Note for the agent fixing "leverage stuck": this cap is a likely cause) |
| 4 | high | **Account says no positions while a real one is open.** /account Positions tab: "No open positions." Same moment: Portfolio shows ETH short $11.67 at 15x, and Account's own Direction bias shows "$11.7 Short". The copy lives in the Copytrade bucket ($0.76 in the equity bar) and the Positions tab only reads the main perps balance | Positions tab merges main + copytrade positions with a "Source" column (Manual / copycat), or the tab label says "Manual positions" and links to Portfolio |
| 5 | high | **"Your copy" column shows money that is not invested.** On Trade (real), 0x0c4a…1b19 has exposure $0.00 and 0 copies ("Only new positions" is on), yet the positions table shows "YOUR COPY $155.88 15x" and "$18.98 10x" as if held. Values also jump between the client estimate and engine preview within seconds ($259.80 → $155.88; "Invest $3,924 → $6,393 to copy their full book") | Label the column "Would copy" when not held, and show "held" vs "next trade" state per row. Show only the engine preview once it lands; keep the estimate visually provisional (muted, "estimate" tag, no colored numbers) |
| 6 | high | **"Wallet" means two different things.** Nav "Account" → button "Wallets" → dialog "Trading accounts" (your Hyperliquid accounts). Trade "Your wallets", Settings "Leaders", Scout "Add to book", Portfolio "Leader" column, Trade "In your book" all mean the traders you copy. "Book" also means "a trader's positions" ("copy their full book", "his whole book runs at 2.2x") | Pick one noun each: **Account** = your HL account (rename "Wallets" button and dialog to "Accounts"); **Trader** = someone you copy; **Copies** = your copied traders ("Your copies", "Copying" badge). Drop "book" and "leader" from UI copy. One glossary in `src/lib/labels.ts` |
| 7 | high | **Discover liquidation counts disagree on the same row.** Liquidations column 1 / 2 / 3 / 4 vs flag badge "liquidated x2 / x3 / x4 / x5" for the same wallets. Column reads `t.sim_liquidations`; badge counts entries in `t.flags` (`DiscoveryTable.tsx:147` vs `:153-157`) | Derive the badge count from `sim_liquidations`, or drop the count from the badge |
| 8 | high | **Primary action hidden below the fold.** At 1456x835 the Trade ticket is an inner scroll area; "Copy wallet" sits at y≈1043 and "No changes / Stop copying" plus the preview's liquidation line are cut off. Users must find a nested scrollbar to act | Pin an action bar at the bottom of the ticket: one summary line (exposure, margin, liq distance) plus the button (DESIGN.md 5, Ticket) |
| 9 | high | **Strategy heatmap shows invented cells.** "When he enters" draws a 7x24 grid whose cells are the product of hour totals and weekday totals; the caption admits "cells combine the two (the api sends totals per axis, not per cell)". It looks like real per-hour-per-day data | Draw two bar charts (by hour, by weekday) until the api returns a real matrix, or add `entries_by_dow_hour` to the contract |
| 10 | high | **Invest, margin and exposure do not add up for a newcomer.** Demo $1K: Invest $100 → "Target exposure ≈ $217.96", "Est. margin $13.94", and after Copy "Free $986.14". Copy text says "Your budget for this wallet. Copies use it as margin", but only $13.94 is used. acct=small: Invest $15 → margin $1.05, then "Invest $48.00 to copy their full book" on a $20 account | Rename to "Allocation", show a 3-line breakdown under the input: "Margin used now $13.94 · Exposure $217.96 (2.2x his book) · Reserved for his next trades $86.06". When the "full book" amount exceeds equity, say "needs $48; you have $20" in `--warn` |

---

## Page by page

### First visit and global shell

| Sev | Finding | Fix |
|---|---|---|
| medium | Real first visit lands on Trade with an already-selected wallet and no onboarding; demo shows a good 1-2-3 strip ("Pick a wallet / Invest $ / Watch it"). The real app is the one that needs it | Show the strip to real users until their first copy; dismiss persists per browser |
| medium | Nav container (`max-w-[1440px]`) and page container (`max-w-6xl` in `layout.tsx`, Trade breaks out wider) do not align; the logo floats left of every page edge | One container width per page type, nav uses the same (DESIGN.md 3.6) |
| medium | 390px: nav is 6 unlabeled icons (Portfolio wallet icon vs Account person icon are easy to confuse); the active label is hidden under 480px | Bottom tab bar with labels on mobile; Settings into the account menu |
| low | "no API token set" warning is `lg:` only; on smaller screens a tokenless user gets no hint until a page errors | Show a key-icon dot badge at all sizes |
| low | Account chip shows the raw label "mainn" (typo in the stored label) beside a truncated address | Nothing to fix in code; Rename exists. Consider showing address only when label is empty |
| low | Next.js dev "N" badge overlaps the bottom-left of every page at 390px | Dev only; ignore or `devIndicators: false` |

### Trade (real)

| Sev | Finding | Fix |
|---|---|---|
| high | Findings 3, 5, 8 above | |
| medium | "INDEX 115.82" is the headline number of every wallet with no explanation on the page (demo explains it in the onboarding strip only) | Tooltip / info icon: "Growth of $100 since tracking began, deposits removed" |
| medium | Wallet name truncation differs on one screen: list "0x0c…1b19", header "0x0c4a…1b19" | One `shortAddress()` everywhere (6…4) |
| medium | Positions table clips the UPNL (ROE) column at desktop width with no scroll cue | Right-edge fade mask + horizontal scroll, sticky first column |
| medium | "Settings: Use global / Custom for this wallet" is preselected to Custom for a wallet you have not copied yet; the "Margin" row is labeled GLOBAL while being editable in Custom mode, so it is unclear whether toggling it changes the global value | Default to "Use global" for new wallets; mark rows that are global-only as read-only with a "change in Settings" link |
| medium | Preview row text "concentrate: slice $0.02 under the $10.5 minimum, allocation goes to his bigger positions" leaks the internal mode name; demo says "under $10 min: moved to his bigger bets" (different minimum, different wording) | One message: "Too small to open (min $10.50). Its share goes to his larger positions." from a shared formatter |
| medium | "Only new positions is on: nothing he holds now is copied" grammar, and the setting it refers to is not linked | "Copying new trades only: his current positions are skipped. [Change]" |
| medium | Pronoun "his" everywhere (ticket, preview, Strategy, What-if) assumes a male trader | "their" |
| low | Leverage slider ticks 1x/10x/25x/50x are evenly spaced on a linear track, so 10x is drawn at 1/3 instead of 18% | Position ticks at real values or use a log scale |
| low | "24H ⇄" column header is a hidden toggle to 7d | Small segmented "24h / 7d" control |
| low | Heat words ("spicy", "brisk", "relaxed") are cute but unexplained; "spicy" for 15x and 25x alike | Tooltip with the liq distance; or replace with the distance itself ("liq at -5.7%") |

### Trade (demo, small, large)

| Sev | Finding | Fix |
|---|---|---|
| medium | After "Copy wallet", the Markets list silently switches to the "My wallets" tab, so the other 25 wallets disappear | Stay on the current tab; show a toast "Copying 0x30ca…3151" with a "View" action |
| medium | Clicks right after navigation land before the ticket is interactive; typed digits are lost (observed twice on `acct=small`/`acct=large`) | Render the ticket input disabled with a skeleton until ready, or keep the same input across the remount |
| medium | Double focus ring on the Invest field (wrapper and inner input both draw orange rings) | Ring on the wrapper only (`:focus-within`) |
| medium | `acct=large` $50K preview shows "Liquidation ~1.5% adverse move at 40x" in muted text; the most dangerous fact on the ticket has the least emphasis | Liq distance under 10% in `--down`, under 25% in `--warn`, with an icon |
| low | In-memory demo book resets on full reload (Portfolio shows "No wallets yet" right after a demo copy) | Persist demo book in `sessionStorage` |

### Scout

| Sev | Finding | Fix |
|---|---|---|
| high | Raw enum `non_perp_ignored` printed on cards and the trader header. `FLAG_TEXT` in `src/lib/scout/labels.ts:61` has no entry, so `FLAG_TEXT[f] ?? f` falls through | Add "spot / HIP-3 holdings ignored by the sim"; gate test that every flag key from the contract has a label |
| medium | Card copy line "Your copy +37 · Sharpe +15 · Green days +10" reads like returns; they are score points | "Score: copy result 37 · Sharpe 15 · green days 10 (of 100)" or a small stacked bar with legend |
| medium | Card "If you copied (30d) +0.0% · DD -0.0%" for the top-ranked trader (score 90) while PnL is +$706K. Score and sim result contradict at a glance | Explain on hover: "No trades opened since you started copying" or show the sim window |
| medium | "$ / %" toggle and grid/list icons have no visible labels | Text labels ("Show $", "Show %") or tooltips |
| medium | /discover was reachable only from a small "Run a custom sim" link (that drops `?demo=1`) and from Settings > Leaders. A Scout sub-nav is being added in the working tree; keep it and preserve query params | Keep "Leaderboard / Custom sim"; links use the demo-preserving helper from `TopNav.tsx` |
| low | "XYZ" prefix chip on HIP-3 coins is unexplained | Tooltip "HIP-3 market (xyz deployer)" |
| low | Sim status chip "refreshing sim 8% · ~9m left · 299 ranked" is good; "Refresh" next to it does not say it restarts a 9-minute job | Confirm or disable while running |

### Trader page and Strategy tab

| Sev | Finding | Fix |
|---|---|---|
| high | Finding 9 (synthesized heatmap) | |
| high | Numbers disagree on one page (demo slow_hands): stats table "Round trips 30d 112, Win rate 63%"; Strategy "Trips analyzed 169 last 30 days, Win rate 57%". Leverage tile "1.38x" vs Strategy "Leverage 6.8x avg". Different definitions, same labels | Rename: "Account leverage now 1.38x" vs "Avg trade leverage 6.8x"; Strategy states its trip definition ("incl. partial closes") or uses the same round-trip source |
| medium | Tabs (Positions, Round trips, Fills, Open orders, Strategy) sit below the Daily PnL calendar, two screens down; users read the chart and miss them | Tabs directly under the Performance chart (DESIGN.md 6) |
| medium | Real Strategy tab: "Reading his fills and candles to build the fingerprint (0/1). This page checks back every few seconds." No ETA, jargon "fingerprint" | Progress bar with step names; "Building strategy summary (about 30s)" |
| medium | Two "Add to book" buttons on one page (header and What-if panel) plus a disabled "Save as this leader's override" | One primary "Copy on Trade" in the header that opens Trade with this trader selected; What-if keeps "Save these terms" |
| medium | "His return +201%" vs "Your copy (sim) +2.6%" on one axis with no explanation; looks like copying destroys the edge | Caption: "Your copy uses your sizing ($1,000, 19% sleeve), so returns are on your equity, not his" |
| low | "Leverage 8.9973x" unrounded; "1 trips", "0 trips" with $588.7K volume | Format to 2 decimals; pluralize; "0 trips" → "open only" |
| low | Calendar red/green cells are hard to separate under deuteranopia (measured dE 13 to 21) | Diverging ramp per DESIGN.md 3.3, per-cell `aria-label` |

### Portfolio

| Sev | Finding | Fix |
|---|---|---|
| blocker | Finding 2 (Day P&L) | |
| medium | "Halt" and "Close all copies" are the largest, most colorful controls on the page, top-right, one click from the title | Move into a "Danger zone" menu on the status strip; keep both behind confirms |
| medium | "Stops new copies. Exits keep mirroring." is jargon | "Stops opening new copies. Closes still follow the trader." |
| medium | Event feed is live-only: "No events yet" while a copy is open, because nothing happened since page load | Load the last 50 events from the api on mount, then stream |
| medium | "SHORT" badge is red, "live orders" badge is red: side and status read as losses | Neutral side pills; status colors per DESIGN.md 3.4 |
| low | Column names drift: "UPNL", "uPnL", "UPNL (ROE)", "Liq. px", "TO LIQ" across Trade / Portfolio / Account | One column vocabulary |

### Account and wallet manager

| Sev | Finding | Fix |
|---|---|---|
| high | Finding 4 (Positions tab misses copy positions) | |
| medium | Real /account sat on a blank skeleton for 15s+ (accounts loaded in 4ms; `/summary` takes ~3.4s per call and the page waits on it with no label) | Render header from `/api/accounts` immediately, skeleton only the summary panels, show "Loading balances…" |
| medium | Real header shows only "Wallets"; demo shows Deposit / Move / Withdraw / Send. Users of the real app cannot find how to fund | Show the same actions in both, disabled with a reason when not available |
| medium | Jargon: "PnL cohort: Net losing", "Size cohort: S", "Signed", "Agent active" | Plain words: "Overall: down $444", "Account size: under $10k"; tooltip for "Agent: copycat can trade, cannot withdraw" (the dialog already says this well) |
| low | PnL chart y-axis labels "$0, -$2, -$5, -$7" (uneven rounding of -2.5 / -7.5) while headline says "-$8" | Nice-number ticks (0, -2, -4, -6, -8) |
| low | "Direction bias" bar is solid red for "Strongly short" | Neutral two-tone bar; red only for losses |

### Settings (look only; another agent is on "leverage stuck")

| Sev | Finding | Fix |
|---|---|---|
| blocker | Finding 1 (demo shows and edits live settings) | |
| high | Three leverage controls on one page plus one per wallet on Trade: Engine "Leverage 15x" (fixed mode), Trade defaults "Default leverage 5x", Copy behavior "Maximum position leverage 15x", and per-wallet 25x/50x on Trade. The effective value is the min of a chain nobody can see | One "Leverage" section: default for new copies, hard cap, and a computed line "Effective for 0xa38f…: 15x (wallet 50x, capped)" |
| high | Two sizing models: Settings "Proportional, Equity sleeve 19%, multiplier 1" vs Trade "Invest $X per wallet". Leader rows read "invested $ (Trade) · 15x", which looks like a missing amount (`LeaderRow.tsx:18` is a static label) | Say which model is active per wallet: "Sized by Trade: $12.29" vs "Sized by sleeve: 19% of equity" |
| medium | "Leaders 2/25" cap vs site description "Mirror up to 10 wallets" (`layout.tsx:20`) vs `MAX_LEADERS = 25` in `contracts/models.py:23` | Update the description to 25 |
| medium | Real-money toggles (Trading enabled, Dry run) sit mid-list with the same styling as cosmetic rows; state is color-only | Top "Live trading" panel, state words "Live" / "Off" |
| low | Discover still says "Simulate with my current /copy settings"; "/copy" is a dead route that redirects | "my Settings" |
| low | One unlabeled range input on the page (a11y scan: `input[type=range]` without label) | `aria-label` or `htmlFor` |

### Discover

| Sev | Finding | Fix |
|---|---|---|
| high | Finding 7 (liquidation count mismatch); finding 1 (demo leak) | |
| medium | Best score in the table is **-10.42**; 21 of 25 rows are exactly -200.00 ("too few trades"). Scout uses 0 to 100 "Copy Fit"; Discover uses an unbounded score. Same idea, two scales | Map to the Copy Fit 0 to 100 scale, or label "Discover score (lower is worse, -200 = not enough data)" and sort ineligible rows to the bottom under a divider |
| medium | "Copy" button clipped at the right edge of the table at desktop width; it is a money action that is half visible | Sticky actions column or row overflow menu |
| low | Max DD shown as negative red "-3.6%" next to Sim return "-2.1%" in the same red; drawdown is a magnitude | "3.6%" in muted, red only when above a threshold |

---

## Real vs demo mismatches

| What | Real | Demo |
|---|---|---|
| Onboarding strip on Trade | none | 1-2-3 strip |
| Settings / Discover | live api | **also live api** (blocker) |
| Account fund actions | "Wallets" only | Deposit / Move / Withdraw / Send |
| Account identity | header chip and /account agree (0x2c2e…6985) | header chip "Main 0x7a…0911", Portfolio "account 0x0000…ffee", Account $754,856 vs Trade/Portfolio $1,000 |
| Portfolio | Halt, Close all, Event feed | none of those |
| Copy behavior | "Only new positions" on: nothing copied now | copies all current positions immediately |
| Under-minimum wording | "concentrate: slice $0.02 under the $10.5 minimum…" | "under $10 min: moved to his bigger bets" |
| Engine mode | trading on, live orders | dry run |

Fix: one `demo` context consumed by every page (nav, Trade, Scout, Portfolio, Account, Settings, Discover), with fixtures that agree on one account (equity, address) per `acct=` value, and demo settings that match the real defaults.

---

## Accessibility

| Sev | Finding | Fix |
|---|---|---|
| medium | Color-only signals: PnL (no glyph in tiles), side (red/green), calendar cells, real-money switch state | Signs/glyphs, neutral sides, `aria-label` per cell, state words |
| medium | Light theme `--warning #a6650a` is 4.30:1 on bg and 4.01:1 on surface-2 (fails AA for the small text it is used on) | `#8f5a00` (5.40 / 5.12), DESIGN.md 3.2 |
| low | Scout page has two `<h1>`; /account rendered none while loading | One h1 per page |
| ok | Automated scan of Trade, Scout, Portfolio, Settings, Discover: 0 controls without accessible names, 0 unlabeled inputs except one range on Settings; tablists and radiogroups have `aria-label`s; Market rows are buttons with `aria-current`; Escape closes the Trading accounts dialog | Keep |

## Mobile (390px)

| Sev | Finding | Fix |
|---|---|---|
| high | Trader page scrolls horizontally (`scrollWidth` 673 vs 390); Trade too (593 vs 390): Markets table clips the FIT column and "every wallet is a m…" | No route may exceed the viewport width (gate test); tables to stacked cards under 640px |
| medium | Trade: demo strip + onboarding take the whole first screen; ticket is three screens down | Collapse onboarding to one line on mobile; sticky bottom sheet with amount + Copy |
| medium | Portfolio: Close all and Halt are the first thing under the title, oversized | Danger menu |
| low | Portfolio wallets table cuts at "LEVERAGE" with no scroll cue | Fade mask + scroll, or cards |
