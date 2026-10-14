# The underwhelm sweep, 2026-10-14

Agent D (qa2 swarm), branch `qa2/sweep`, base `d3b3fec`. Operator's ask verbatim: "make sure there are
no other trivial waste of time unimpressive things that will make a user be underwhelmed exists on the app."

## Method

Walked every page (`/`, `/scout`, `/scout/[address]`, `/portfolio`, `/account`, `/settings`) at 1440x900 and
390x844, dark and light, demo mode (`?demo=1`, deterministic fixtures) and a full mock-HL stack
(`E2E_STACK=full`, `e2e/mock_hl`), empty/loading/error/populated states where reachable, plus a keyboard-only
pass. `/discover` was walked read-only and otherwise left alone (agent A is removing it this round).

The tool: `e2e/tests/visual/sweep.spec.ts`, `test.skip` unless `E2E_SWEEP=1`, writes PNGs to
`e2e/artifacts/sweep/<page>-<state>-<width>-<theme>.png` (gitignored, regenerate on demand, see
`e2e/artifacts/sweep/`'s path column below). Regenerate everything:

```
cd e2e
E2E_SWEEP=1 npx playwright test --project=visual -g sweep                       # demo-mode scenarios
E2E_STACK=full E2E_SWEEP=1 E2E_PYTHON=~/Documents/code/copycat/.venv/bin/python \
  npx playwright test --project=visual -g "fresh install"                       # no-account states (mock HL only)
```

Full-mode runs here only ever talked to `e2e/mock_hl` (`COPYCAT_HL_BASE_URL` pinned to it, `COPYCAT_E2E=1`),
never real Hyperliquid, and never touched `:3000`/`:8787`/`./data`. Every throwaway stack's `stopStack()` ran
cleanly; no process or temp dir of this agent's outlived its test run (checked with `lsof`/`ps` after each run).

### Two methodology bugs in the sweep tool itself, not the product

Found and fixed before trusting any screenshot below:

1. **Reveal-on-mount hides below-the-fold content in a `fullPage` capture.** `components/shell/Reveal.tsx`
   only marks `[data-reveal]` elements visible once a real scroll brings them into the viewport. A `fullPage`
   screenshot resizes the viewport to the full scroll height for one shot without actually scrolling there
   first, so anything that mounted below the first screen got captured mid-fade at opacity 0. First symptom:
   the 36-row Scout board screenshotted as 3 cards and a wall of blank space. Fix: every scenario now calls
   `page.emulateMedia({ reducedMotion: "reduce" })` first, which is also the condition under which
   `Reveal.tsx` itself skips the hidden-until-scrolled behavior entirely ("without JS, or under reduced
   motion, nothing is ever hidden") — so this isn't a workaround, it's the documented escape hatch.
2. **`position: fixed` elements double-paint in a `fullPage` capture.** The Trade page's mobile bottom-sheet
   ticket (`#ticket`, `max-lg:fixed max-lg:bottom-0`) and `BottomTabBar` (`.vt-tabbar`, `fixed bottom-0`) keep
   their on-screen offset from the *original* viewport when Chromium resizes it taller for the stitched
   capture, so they paint mid-page, overlapping real content. Fix: `sweep.spec.ts`'s `shot()` hides both via
   an injected stylesheet before any `fullPage` capture under 1024px; the three Trade scenarios instead take a
   plain viewport screenshot (`mobileFullPage: false`) so the ticket is seen the one correct way a phone
   actually shows it.

Neither is a real user-facing bug (no real browser scrolls instantly to the full page height without
rendering the frames in between), but both would have produced false findings below if not caught.

## Findings fixed in this branch

| # | Page / file | State | What underwhelmed (exact text / pixel) | Severity | Fix | Evidence |
|---|---|---|---|---|---|---|
| 1 | Scout board, card footer — `components/scout/TraderCard.tsx` (`IfCopied`) | Any card with a sim | `IF YOU COPIED 30D -0.4% · max dip 0.0% · capacity 4% · 100% of skipped opens: under the $10.50 minimum order at your size` — four facts dot-joined, the one that mattered (most opens never fit) buried last | high: wrong is-strong-at-a-glance read; starved capacity looked like a footnote | New `ifCopiedText()` (`lib/scout/copyFit.ts`) builds it as sentences: *"Your copy, 30d: +16.3%, worst dip 17.1%. Only 78% of their opens fit your size; the rest were under the $10.50 minimum order at your size."* Reads the same way in the good case too: *"100% of their opens fit your size."* The "If you copied, 30d" label above it was dropped (now redundant — the sentence says it). | Before: `/tmp` crop taken pre-fix (not preserved; reproduced any time from `d3b3fec`). After: `e2e/artifacts/sweep/scout-board-1440-dark.png`. Tests: `lib/scout/copyFit.test.ts` ("ifCopiedText…", 6 cases incl. they/their). |
| 2 | Trader file header — `components/scout/file/FileHeader.tsx` | Any flagged trader | Every flag rendered as an uppercase mono `tone="warning"` pill, including `fills_truncated` ("ONLY THE LATEST 10K FILLS ARE VISIBLE") and `non_perp_ignored` ("SPOT / HIP-3 HOLDINGS IGNORED BY THE SIM") — scope disclaimers shouting like alarms, and `fills_truncated` duplicated the non-binding Copy Fit cap line already shown in the breakdown popover | medium: miscategorized severity reads as "something's wrong" when nothing is | `FileHeader` now calls `visibleFlags()` (drops `fills_truncated`, already the TraderCard convention) and a new `flagTone()` (`lib/scout/labels.ts`): `non_perp_ignored`, `candles_partial`, `stale` are `neutral`; everything else stays `warning` (defaults to `warning` for an unknown future flag, never silently neutral) | Tests: `lib/scout/labels.test.ts` ("flagTone: a scope disclaimer is neutral…", "…stays a warning", "…defaults to warning"). a11y scan of the trader file still 0 violations (`e2e/tests/a11y/scout.spec.ts`). |
| 3 | Trade ticket, Set leverage — `components/trade/LeverageField.tsx` | Leverage above the Settings cap | `50x → 1x cap: Maximum position leverage in Settings caps it, so copies open at 1x.` — states the bad news, gives no way to act on it, even though per-wallet leverage already lives right here | medium: dead end, no next action | Appended a `Raise the cap` link to `${settingsHref}#max_position_leverage` (the exact slider's `id`, so the browser scrolls straight to it); threaded a new `settingsHref` prop through `Ticket.tsx` → `LeverageField.tsx` | After: `e2e/artifacts/sweep/trade-leverage-capped-1440-dark.png` and `-390-dark.png`. Test: `e2e/tests/demo/trade.spec.ts` "leverage cap message offers a way to raise it…" (sets the cap to 1x in Settings, confirms the link's href and that the target is in viewport after following it). |
| 4 | Portfolio, empty Positions — `components/positions/PositionsTable.tsx` | Zero open positions | `No open copies… Check your copies` linked to `/copy` — a **removed legacy route** (`lib/trade/apiState.ts` `LEGACY_ROUTES`) that redirects to **`/settings`**, not to the wallets list (titled "Your copies") sitting directly above it on the same page | high: a link that actively sends the user to the wrong page, on the one row most likely to be clicked by someone wondering "do I even copy anyone" | Re-pointed to `#your-copies`, a same-page anchor; gave `YourWallets.tsx`'s "Your copies" `<h2>` that `id` | After: `e2e/artifacts/sweep/portfolio-empty-1440-dark.png`. Before: `/tmp/portfolio-empty-BEFORE.png` (this session only). Test: `e2e/tests/demo/portfolio.spec.ts` "'Check your copies' jumps to Your copies on this page, not a dead /copy route" (asserts the href, follows it, confirms the heading is in viewport). |
| 5 | Any page's first load — `components/PageStates.tsx` (`PageSkeleton`) | Slow route chunk (real-world: a loaded dev box, a slow connection) | Three empty pulsing boxes, no visible text, for however long the Suspense fallback shows (operator: "a bare skeleton for more than 2s, then the page"). The loading label existed only `sr-only` — a screen reader heard "Loading account", a sighted user saw nothing | medium: looks broken, not loading, on exactly the UX audit's "spinners longer than a second with no words" test | Loading label is now visible text with a spin icon (`<Loader2/> {label}…`), not `sr-only`; `role="status"` still announces it to AT, so nothing is lost there | Before: `e2e/artifacts/test-results/account-demo-Account-loadi-93f7c-are-pulsing-boxes-QA-audit--demo/test-failed-1.png` (captured by deliberately reverting the fix to confirm the test catches it — see test). Test: `e2e/tests/demo/account.spec.ts` "loading shows visible text, not three bare pulsing boxes" (throttles script responses so the fallback is guaranteed visible, asserts the text, confirmed it fails against the pre-fix component). |
| 6 | Settings: Sizing mode, Leverage mode — `components/copy/EngineControlsPanel.tsx`; Trade ticket Settings toggle — `components/trade/Ticket.tsx` | Every load, 1440px **and** 390px (not only narrow screens — the opposite of the usual mobile-truncation bug) | `Fixed marg…`, `Fixed notio…`, `Match trad…` in Settings (the control's value column is a flat `sm:w-80` = 320px regardless of screen width, below `sm` it's `w-full` instead, so **desktop truncated and mobile didn't**); `Custom for this tra…` in the Trade ticket's narrower column | medium: "labels that truncate" — explicit hunt-list item, and surprising since it got *worse* on the wider screen | `ui/Panel.tsx` `SettingRow` takes an optional `valueClassName` (default unchanged for every other row); the two Settings rows pass `sm:w-96`. The ticket's option is genuinely narrow at any screen size, so its label is shortened to `Custom` (the group's own `aria-label="Settings for this trader"` already carries the rest; no other string in the codebase used the long form) | Before: `/tmp/lev_mode_1440b.png`, `/tmp/sizing_mode.png` (this session only). After: `e2e/artifacts/sweep/settings-1440-dark.png`, `e2e/artifacts/sweep/trade-empty-1440-dark.png`. Test: `e2e/tests/a11y/account_settings.spec.ts` "no SegmentedControl option text is clipped" — scans every `role="radio"` on Settings for `scrollWidth > clientWidth`, generic enough to catch a *future* label getting too long too, not just these two; confirmed it fails without the width fix. |

## Follow-ups (not fixed here — need another agent, a backend change, or Julien's call)

| Where | What | Why not fixed in this branch | Severity |
|---|---|---|---|
| `components/copy/LeadersPanel.tsx:79` | Empty Copies list links to `/discover` ("find one on Discover"). **Correct today** (Discover is still live on this branch's base), but agent A is removing `/discover` and `scoutNav.ts`'s `SCOUT_TABS` this round. This file is outside the stated exclusion (`components/discover`, `app/discover`), so it will dangle unless agent A's removal also updates it (or Scout's "Custom sim" concept gets a new home this link should point at instead). | Cross-agent: fixing it now means guessing at agent A's landing design; not fixing it risks a dead link post-merge | high once Discover lands removed, zero today — flag at merge time |
| Scout board header (`app/scout/page.tsx`, not mine) | "0 wallets left the top 300 this month, 3 by liquidation." reads self-contradictory (0 left, but 3 left "by liquidation"?) in demo fixtures; live screenshot in the brief showed "99 wallets left…". Worth a second look at the sentence construction. | File excluded (agent A's note/toolbar) | low-medium, agent A |
| `components/scout/bits.tsx` refresh badge (RefreshBadge, not mine) | Brief: "badge 'refreshing stats 2% ~394m left'" — ETA math is agent B's to fix; could not independently judge placement/wording since demo fixtures never render the in-progress refresh state (only "refreshed Xm ago"). | File excluded (agent B's component); state not reproducible outside a live refresh cycle | n/a — agent B |
| Trade-side copy: `AdvancedFields.tsx`, `TicketDialogs.tsx`, `YourWallets.tsx`, `ProjectionPanel.tsx`, `IndexChart.tsx`, `lib/trade/*` (dozens of files) | Consistently use "he/his/him" for the trader being copied. Scout's own copy (`FLAG_TEXT`, `PART_META`, `CAP_RULES`, now `ifCopiedText`) is held to "they/their" by two vitest guards. The two halves of the app disagree with each other, each consistently within itself. | Picking a direction here means rewriting pronouns across ~30 files well past "one-line wording fix" — a real scope decision, not a QA-sweep call | low (internally consistent either way; only visible if you use both Trade and Scout back to back) — **Confusion Protocol**: pick one convention and say so, then it's a mechanical follow-up |
| Top nav account chip, "mainn 0x2c…6985" (operator's live screenshot) | Looked for a truncation bug (`AccountSwitcher.tsx`, `AddressChip.tsx`, demo + full-stack fresh-install flows) and could not reproduce it: no string in the codebase renders a lowercase "mainn[et]" prefix next to an address; `AccountSwitcher`'s label is the account's own name (demo: "Main"), not the network. Likely either a one-off mid-transition frame in that screenshot, or specific to the operator's own account label on the live stack. | Not reproduced | unknown — needs the operator's real screenshot or live repro, not guessable from demo data |
| Copy Fit "not simulated" capacity cell — `components/scout/TraderTable.tsx` | Capacity column shows a bare `—` when `sim_copy_capacity_pct` is null, with only a `title` tooltip (unreachable by keyboard) for why. In every fixture row this coincides with the adjacent "If copied" column already showing `none` with its own explanatory title, so the reason isn't actually hidden, just not keyboard-reachable from *this* cell specifically — same as every other dense column in this table (Sharpe, Max DD, …), so fixing just this one cell would be inconsistent with the table's existing convention rather than better | low — logged, not changed, to avoid a one-off inconsistent fix in a shared table | low |

## Gate

Python: `pytest -q` all pass (zero files touched); `ruff check contracts services` 69 pre-existing findings,
all outside files this branch touched (verified: none of the 34 flagged files overlap this branch's diff).
Web: `npm run lint` / `npm run typecheck` / `npx vitest run` — 734/734 passed. e2e: `npm run demo`
(demo + a11y + visual projects) — 45 passed, 44 skipped (the sweep tool itself, gated on `E2E_SWEEP=1`).
Full numbers and commit list in this agent's final report to the operator.
