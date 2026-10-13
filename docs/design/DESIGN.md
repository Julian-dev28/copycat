# copycat design system

Status: proposal, ready to implement. Owner: web (`services/web`). Companion: [UX_AUDIT.md](./UX_AUDIT.md).

Goal: make copycat feel as smooth as the operator's site (https://julianmartinez-delta.vercel.app/) **without** losing what a trading screen needs: density, legible numbers, and colors that stay calm while money is moving.

Everything here maps to Tailwind 4 `@theme inline` tokens in `src/app/globals.css`. No new runtime dependencies. Motion is CSS only (transitions, `@starting-style`, keyframes, View Transitions); no animation library.

---

## 1. What the reference site does (measured)

Read from its stylesheet (`/_next/static/chunks/3mp0hmzdpduwz.css`) and markup on 2026-10-05.

| Area | Value |
|---|---|
| Canvas | `--color-bg: #000`. Body gets two fixed radial glows: `radial-gradient(55% 45% at 82% -8%, #4d90ff1a, transparent 60%), radial-gradient(45% 38% at -5% 8%, #ff6a3c0f, transparent 60%)`, `background-attachment: fixed` |
| Ink scale | ink `#f5f5f7`, ink-soft `#d6d6db`, muted `#8e8e93`, faint `#5e5e63`, hairline `#ffffff1a` |
| Accents | primary blue `#4d90ff`, warm secondary `#ff6a3c` (glow only), teal status dot `#2bb3a3` with `animate-pulse` |
| Type | Geist (sans), Geist Mono (labels, metadata, nav), Instrument Serif italic (one or two display words per heading). Hero `clamp(2.5rem, 6.4vw, 5.6rem)`, weight 500, leading 0.98, tracking -0.02em. Section titles `clamp(2rem, 4.5vw, 3.4rem)`. Labels `11px`/`12px` mono, uppercase, tracking `0.05em` to `0.18em` |
| Text use | `text-muted` 156 uses, `text-[11px]` 98, `font-mono` 187: most of the page is small mono metadata around a few large statements |
| Spacing | 4px base (`--spacing: .25rem`). Sections `py-24`, cards `p-7`, chips `px-2.5 py-1`, gaps 8 to 16px. Container `max-w-6xl` (72rem) with `px-6 sm:px-10` |
| Radii | `rounded-full` for chips and buttons (90 uses), `rounded-2xl` (16px) cards, `rounded-xl` (12px) inner media |
| Glass | `.glass { backdrop-filter: blur(22px) saturate(180%); background: #ffffff0d; border: 1px solid #ffffff1a; box-shadow: inset 0 1px #ffffff0f, 0 20px 50px -20px #0009 }`. Hover: bg `#ffffff14`, border `#ffffff2e`, `transition: background .35s, border-color .35s, transform .35s` |
| Reveal | `[data-reveal] { opacity:0; transform: translateY(18px); transition: opacity .8s cubic-bezier(.16,1,.3,1), transform .8s cubic-bezier(.16,1,.3,1); transition-delay: var(--reveal-delay) }`, staggered 0 / 80 / 160ms via IntersectionObserver |
| Header | `fixed`, `h-16`, transparent, then `bg-paper/80 backdrop-blur-md` + hairline once scrolled (`transition-colors duration-500`). A 1px accent scroll-progress bar under it |
| Micro-motion | links `group-hover:translate-x-0.5` / `-translate-y-0.5` on the arrow, `duration-300`; marquee 42s linear with an 8%/92% edge mask |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` turns off smooth scroll, reveal and marquee |
| Selection, scrollbar | `::selection { background: #4d90ff; color: #fff }`; 10px scrollbar, thumb `#2a2a2e` with a 3px black border, fully rounded |

**Why it feels "flowy":** one cool canvas with soft colored light, hairline borders instead of boxes, everything rounded, a single slow easing (`cubic-bezier(.16,1,.3,1)`, an expo-out) used everywhere, content that arrives in a short stagger, and a strong contrast between a few big confident type moments and lots of quiet small mono metadata.

### Take vs leave

| Take | Leave |
|---|---|
| Cool near-black canvas, two faint fixed glows (blue top-right, ember top-left) | Pure `#000` everywhere: panels need 3 to 4 elevation steps to separate dense data |
| Hairline borders (`white/8` to `white/10`), inset top highlight on raised surfaces | Heavy `backdrop-filter` on every card: costly over live tables and charts. Glass only on sticky header, popovers, dialogs, toasts |
| One easing curve (expo-out) and a short duration ladder | 800ms reveals and 18px slides on data. Trading data must never be invisible or late. Reveal page sections once, at most 240ms, never rows or numbers |
| Mono uppercase micro-labels with tracking | Mono for prose. Mono stays for numbers, addresses and labels only |
| Serif italic for one word in a page title or empty-state headline | Serif anywhere near numbers, tables, or forms |
| Fully rounded pills for chips, tabs, segmented controls, small buttons | 16px radii on dense table containers (use 12px) |
| Scroll-progress hairline | Marquees, parallax, anything that moves on its own near prices |
| Arrow nudge on link hover, glow on primary hover | Hover transforms on table rows (rows must not move) |
| `prefers-reduced-motion` handling | |

---

## 2. Color research summary

Sources are listed at the end of this file. Short version:

1. **Blue is the calm, trust hue for money UIs.** Unsaturated blue reads as security and lowers anxiety when large sums are involved; a sharp accent should be kept for the one primary action (windmill.digital; weandthecolor.com; contra.com "Perpelio").
2. **Red changes behavior, not just mood.** Showing losses in red lowers risk-taking and makes people expect further declines; the same data in blue or black does not (Bazley, Cronqvist, Mormann, "Visual Finance: The Pervasive Effects of Red on Investor Behavior", *Management Science*, 2021; SMU Cox summary). So red must be reserved for losses and true danger, not for "short", not for status badges, not for big chart fills.
3. **Red/green fails for about 1 in 12 men.** Deuteranopia collapses red and green; blue/orange (hue ~220 vs ~30) survives deuteranopia and protanopia (vis4.net "Goodbye red-green"; Bloomberg UX; Futubull's accessibility case study on Android Developers, which also used hollow vs solid candles).
4. **Conventions are regional.** Mainland China, Taiwan and Japan use red = up, green = down; Korea uses red = up, blue = down (Benzinga; W3C i18n list; behavioraleconomics.com "When red means go").
5. **Small numbers need 4.5:1.** WCAG 1.4.3 AA requires 4.5:1 for text under 18pt (14pt bold); every price and PnL figure in the app is small text (Google tech-writing accessibility guide; WCAG).
6. **Peer apps.** Hyperliquid itself: near-black `#04060c` canvas, elevation steps `#0a0d16 / #121622 / #1a1f2e`, mint-teal `#97FCE4` accent, white text at 92% opacity (webdesignhot design.md for Hyperliquid). Robinhood went off-convention with neon `#CCFF00` to stand apart from bank navy.

### Measured: what the current palette does

All ratios computed by script (WCAG relative luminance), not eyeballed.

| Current token | Dark on bg / surface | Light on bg / surface | Problem |
|---|---|---|---|
| accent `#ff7a1a` / `#b04a08` | 7.55 / 7.06 | 5.04 / 5.48 | Passes contrast, but hue sits between danger red and warning amber |
| warning `#ffb020` / `#a6650a` | 10.77 / 10.07 | **4.30** / 4.68 | Light warning fails AA on bg and on surface-2 (4.01) |
| success vs danger, deuteranopia | dE 20.6 (dark), 29.1 (light) | | Weak separation; light pair has luminance ratio 1.04, so they are the same lightness |

### Decision on the orange accent: replace it as the UI accent, keep it as the brand

**Replace** `#ff7a1a` / `#b04a08` as the interactive accent. **Keep** it as `--brand` (the "ember") for the cat logo, the favicon, the "copy" in the wordmark, and one faint background glow.

Why:

- **It collides with meaning.** On a single Trade screen today, orange marks: the active nav item, every selected segmented control, the primary button, the "In your book" badge, mid Copy Fit scores, the dry-run banner, "skipped" rows, "Invest $3,924 to copy their full book", the "spicy" leverage tag and the Strategy tags. Accent and warning are about 15 degrees of hue apart. Users cannot tell "selected" from "careful".
- **It is a stress hue.** Orange sits next to red. A screen that is half orange-filled blocks reads as an alert state, which is what loss-averse users are already primed to see.
- **It fights the PnL colors.** The colorblind-safe PnL pair is blue/orange. With an orange accent there is no colorblind mode left to offer.
- **The reference site already solves it.** Blue `#4d90ff` interactive accent plus a warm `#ff6a3c` glow. copycat can follow the same split: blue to act, ember to be recognized.

The cat stays orange. The logo keeps its identity and stands out more because it is the only orange thing on a calm screen.

---

## 3. Tokens

### 3.1 Color: dark (default)

| Token | Hex | Use | Contrast (bg `#08080a` / surface `#101012` / s2 `#17171a`) |
|---|---|---|---|
| `--bg` | `#08080a` | page canvas | |
| `--surface` | `#101012` | panels, cards | |
| `--surface-2` | `#17171a` | inputs, table headers, segmented tracks | |
| `--surface-3` | `#1e1e22` | hover, selected row, raised popover | |
| `--border` | `#222226` | hairlines (or `rgb(255 255 255 / .08)`) | |
| `--border-strong` | `#303036` | focus-adjacent, input borders | |
| `--fg` | `#ececee` | primary text, big numbers | 17.58 / 16.70 / 15.56 |
| `--fg-soft` | `#c6c6cb` | body copy, table cells | 12.09 / 11.48 / 10.70 |
| `--muted` | `#8d8d96` | labels, captions, secondary numbers | 6.44 / 6.12 / 5.70 (5.20 on s3) |
| `--faint` | `#55555c` | decorative only: grid lines, disabled, separators. **Never text** | 3.49 / 3.32 |
| `--accent` | `#7aa2ff` | links, selected states, primary button bg, focus ring | 8.05 / 7.65 / 7.13 |
| `--accent-fg` | `#050b1a` | text on accent | 7.89 on accent |
| `--accent-soft` | `#181c26` (accent at 14% on surface) | selected pill bg | accent text on it 6.22 |
| `--brand` | `#ff7a1a` | cat logo, wordmark "copy", ember glow. Not interactive | 7.68 / 7.29 |
| `--up` | `#4fbf8f` | gains, positive PnL | 10.22 / 9.71 / 9.05 |
| `--down` | `#ef5a68` | losses, negative PnL | 6.93 / 6.59 / 6.14 |
| `--up-soft` / `--down-soft` | `#132b26` / `#301c22` | PnL cell flashes, chart fills (14%) | up 7.65, down 5.53 on their soft |
| `--warn` | `#f2b544` | caution: dry run, skipped, near-liq, under-minimum | 10.94 / 10.39 / 9.68 |
| `--warn-soft` | `#2e271c` | banner bg | warn text 8.06 |
| `--danger` | `= --down` | destructive buttons, errors, liquidation | |
| `--long` / `--short` | `--fg-soft` + glyph | side labels are neutral (see 3.4) | |

### 3.2 Color: light

| Token | Hex | Contrast (bg `#f7f7f8` / surface `#ffffff` / s2 `#f2f2f4`) |
|---|---|---|
| `--bg` | `#f7f7f8` | |
| `--surface` | `#ffffff` | |
| `--surface-2` | `#f2f2f4` | |
| `--surface-3` | `#e9e9ec` | |
| `--border` | `#e3e3e7` | |
| `--fg` | `#0c0c0e` | 17.75 / 19.03 / 16.83 |
| `--fg-soft` | `#2c2c31` | 12.12 / 12.99 / 11.49 |
| `--muted` | `#5d5d66` | 5.78 / 6.20 / 5.48 |
| `--faint` | `#a1a1aa` | decorative only (2.4 to 2.6) |
| `--accent` | `#2d5bd8` | 5.44 / 5.83 / 5.16 (4.80 on s3) |
| `--accent-fg` | `#ffffff` | 5.83 on accent |
| `--accent-soft` | `#eaeffb` | accent text on it 5.07 |
| `--brand` | `#b04a08` (unchanged) | 5.12 / 5.48. Cat eyes stay `--accent-fg`-style near-white |
| `--up` | `#0b7347` | 5.51 / 5.90 / 5.22; 5.12 on its 10% soft |
| `--down` | `#c0263a` | 5.47 / 5.87 / 5.19; 5.00 on its 10% soft |
| `--warn` | `#8f5a00` | 5.40 / 5.78 / 5.12 (replaces `#a6650a`, which failed at 4.30) |

### 3.3 PnL color modes (user setting, Settings > Display)

| Mode | Up | Down | When |
|---|---|---|---|
| `standard` (default) | `--up` green | `--down` red | Western convention |
| `colorblind` | dark `#4cb0ff` / light `#0a6fc2` | dark `#ff9a2e` / light `#a84f00` | deuteranopia / protanopia |
| `east-asia` | `--down` hex | `--up` hex | CN / TW / JP convention (red up) |

Measured separation (CIELAB delta E after Machado 2009 simulation, severity 1.0):

| Pair | Normal vision | Deuteranopia | Protanopia |
|---|---|---|---|
| current dark green/red | 119.5 | 20.6 | 29.6 |
| current light green/red | 97.5 | 29.1 | 11.9 |
| new dark green/red | 117.5 | 13.3 | 30.5 |
| new light green/red | 98.8 | 21.0 | 12.9 |
| colorblind dark blue/orange | 120.3 | **119.7** | **109.0** |
| colorblind light blue/orange | 107.7 | **107.7** | **94.5** |

Red/green is weak under CVD in every variant, which is why the colorblind mode exists **and** why color is never the only signal:

- every signed number shows its sign (`+$1,204.10`, `-$88.20`), plus `▲`/`▼` in summary tiles;
- charts use line weight or fill, not only hue, to separate "his" vs "your copy";
- heatmaps (daily PnL calendar) use a diverging ramp with a neutral midpoint and a legend; cells carry `aria-label`.

Implementation: `data-pnl="standard|colorblind|east-asia"` on `<html>`, and three small blocks in `globals.css` that only remap `--up`, `--down`, `--up-soft`, `--down-soft`. Components only ever use `text-up` / `text-down`. Never `text-green-*`.

Rule: **the accent never colors a number.** In colorblind mode the accent blue and `up` blue are close (dE 2.1 under deuteranopia), so the accent is restricted to controls, links and focus.

### 3.4 Semantic rules

- **Long / short are not good / bad.** Today `SHORT` is red and `LONG` green, so a profitable short reads as a loss. Side uses neutral text with a glyph: `↗ Long` / `↘ Short` in `--fg-soft`, pill bg `--surface-2`. Only PnL is colored.
- **Status badges are not PnL.** "live orders" currently renders in danger red; it is a state, not an error. Use `--accent-soft` for "live", `--warn-soft` for "dry run", `--surface-2` for neutral, `--down` only for halted, error, liquidated.
- **Score badges (Copy Fit)** use a single-hue accent ramp by bucket (90+, 70 to 89, 50 to 69, below 50), never green/orange/red. A score is a ranking, not money.
- **Leverage heat** ("brisk", "spicy") uses `--warn` only above 20x and `--down` only when the liquidation distance is under 10%.
- **Destructive** buttons (Stop, Close all, Halt) use outline `--down` at rest, filled only inside the confirm dialog.

### 3.5 Type

Keep Geist + Geist Mono (already loaded). Add **Instrument Serif** (italic 400, Google Fonts via `next/font`) for display accents only.

| Token | Size / line | Weight | Family | Use |
|---|---|---|---|---|
| `display` | `clamp(1.75rem, 3vw, 2.5rem)` / 1.05, tracking -0.02em | 500 | Geist (+ serif italic word) | page titles (Scout, Portfolio, Account) |
| `title` | 20 / 28 | 600 | Geist | panel group titles |
| `heading` | 15 / 22 | 600 | Geist | panel headers |
| `body` | 14 / 20 | 400 | Geist | prose, descriptions |
| `small` | 13 / 18 | 400 | Geist | helper text |
| `label` | 11 / 14, uppercase, tracking 0.08em | 500 | Geist Mono | stat labels, column headers |
| `num-xl` | 32 / 36, tracking -0.02em | 500 | Geist Mono, `tnum` | account value, hero stat |
| `num-lg` | 20 / 26 | 500 | Geist Mono, `tnum` | tile values |
| `num` | 13 / 18 | 400 | Geist Mono, `tnum`, `zero` | table cells |
| `num-sm` | 12 / 16 | 400 | Geist Mono, `tnum` | sub-values (ROE, leverage suffix) |

Rules: numbers are always mono with `font-variant-numeric: tabular-nums slashed-zero` and right-aligned in tables. No text smaller than 11px. Units (`x`, `%`, `iso`) are `num-sm` in `--muted`, set after the value with a thin gap.

Serif italic: one word max per title, never in data views. Examples: "Scout the *quiet* winners", empty Portfolio: "Nothing *copied* yet".

### 3.6 Spacing, radius, elevation

**v2 "terminal" (2026-10-14).** The rounded, glowing v1 read as a consumer app. v2 is square, flat and
mono-labelled, after Hyperdash and julianmartinez-delta.vercel.app: near-black neutral surfaces (no blue
tint), 2-3px radii everywhere (`rounded-full` survives only on status dots), no card shadows (a 1px hairline
and a hover fill instead), flat uppercase mono nav with a 1px accent underline, a scroll-progress hairline
under the header, scroll reveal on panels, a ticker strip on Scout, and a long/short stat strip at the foot
of every trader card. Effects taken from the reference: `.glass` with an inset top highlight, the edge-faded
marquee, two faint corner glows on the canvas, `[data-reveal]` rise-and-fade on first view. Contrast is
re-checked by `src/lib/display/tokens.test.ts` on every commit.

- Spacing: 4px base. Dense data rows 36px (`py-2`), comfortable rows 44px. Panel padding 16px mobile / 20px desktop. Page gap 20px. Section gap 32px.
- Container: one width everywhere. Today the nav is `max-w-[1440px]` and `<main>` is `max-w-6xl`, so the logo and the content edges do not line up. Use `max-w-[1360px]` for Trade (3 columns) and `max-w-6xl` for reading pages, and put the nav inside the same container width as the page.

| Radius token | px | Use |
|---|---|---|
| `--r-pill` | 2 | chips, tabs, segmented controls, small buttons, badges (was 999 in v1) |
| `--r-sm` | 2 | inputs, table row hover, menu items |
| `--r-md` | 3 | panels, cards, tables |
| `--r-lg` | 4 | dialogs, drawers, hero cards |

Tailwind's whole `rounded-*` scale is remapped to these in `globals.css` (`--radius-sm` .. `--radius-3xl`),
so no component needs to change its class to stay square. `rounded-full` is reserved for status dots.

| Elevation | Dark | Light |
|---|---|---|
| `e0` flat | `--surface`, 1px `--border` | same |
| `e1` raised card | none: flat `--surface` + 1px `--border`; hover brightens the border and fills `--surface-2` at 60% | same |
| `e2` popover / menu | `--surface-3` + `0 12px 32px -12px rgb(0 0 0 / .7)` | `0 12px 32px -12px rgb(13 16 23 / .18)` |
| `e3` dialog | glass: `rgb(14 16 21 / .82)` + `backdrop-filter: blur(20px) saturate(160%)` + `0 24px 60px -20px rgb(0 0 0 / .8)` | `rgb(255 255 255 / .9)` + same blur |
| glow (primary button hover, focus) | `0 0 0 1px var(--accent), 0 8px 24px -8px color-mix(in srgb, var(--accent) 45%, transparent)` | same at 30% |

Canvas glow (dark only, `body`): `radial-gradient(60% 40% at 85% -10%, rgb(122 162 255 / .08), transparent 60%), radial-gradient(40% 30% at -5% 0%, rgb(255 122 26 / .05), transparent 60%), var(--bg)`, `background-attachment: fixed`. Light mode: same shapes at half opacity.

### 3.7 Motion tokens

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(.16, 1, .3, 1)` | everything that enters or settles (reference site curve) |
| `--ease-in-out` | `cubic-bezier(.65, 0, .35, 1)` | things that move between two states (segmented thumb, tab indicator) |
| `--ease-in` | `cubic-bezier(.4, 0, 1, 1)` | exits only |
| `--dur-instant` | 80ms | press feedback (scale .98) |
| `--dur-fast` | 140ms | hover color, border, icon nudge |
| `--dur-base` | 220ms | segmented thumb, tab underline, popover in, accordion |
| `--dur-slow` | 320ms | dialog / drawer in, page section reveal |
| `--dur-flash` | 900ms | number change flash fade-out |

Exits are 0.75x the enter duration with `--ease-in`.

---

## 4. Motion principles

1. **Data is never late.** Numbers, rows and chart lines render immediately. Motion only decorates arrival (a tint flash), never delays it.
2. **One curve.** Expo-out for entering, in-out for sliding between states. No springs, no bounce.
3. **Move the frame, not the data.** Animate indicators, panels, dialogs, focus rings. Do not slide rows, reorder lists with motion, or count numbers up from 0.
4. **Show change, not noise.** A changed price or PnL cell flashes its `--up-soft` / `--down-soft` background for `--dur-flash` (opacity 1 to 0). Throttle to one flash per cell per 2s so a fast feed does not strobe.
5. **Reduced motion is a first-class mode.** Under `prefers-reduced-motion: reduce`: no translate or scale, no reveal, no flash (use a 2px left border tint that does not fade), no smooth scroll, durations to 0 except opacity fades at 80ms. The existing global `0.01ms` override in `globals.css` stays as the floor.

What animates:

| Element | Animation |
|---|---|
| Segmented controls, tabs | a single `::before` thumb that slides (`transform: translateX`, `--dur-base`, `--ease-in-out`) instead of the selected button repainting as a block |
| Nav active underline | the 1px accent line moves between links; View Transition name `nav-pill` on route change |
| Scroll reveal | `[data-reveal]` panels fade in and rise 12px the first time they scroll into view, 50ms stagger per batch (max 300ms), `components/shell/Reveal.tsx`; off under reduced motion |
| Scout ticker | `components/ui/Marquee.tsx`: the top 12 rows drift left at ~6 s per item, edges fade, hover pauses |
| Panels on first page load | `@starting-style { opacity: 0; transform: translateY(6px) }`, `--dur-slow`, 40ms stagger per panel, max 4 panels. Never on refetch |
| Dialogs, drawers | backdrop fade `--dur-base`; panel `opacity 0 → 1`, `scale .98 → 1` (dialog) or `translateX(16px) → 0` (drawer), `--dur-slow` |
| Popovers, account switcher | `opacity` + `translateY(-4px)`, `--dur-base` |
| Buttons | hover: bg/border `--dur-fast`; press: `scale(.98)` `--dur-instant`; primary hover adds glow |
| Links with arrows | arrow `translateX(2px)` on hover, `--dur-fast` (reference pattern) |
| Live dot ("engine running") | 2s opacity pulse `1 → .45 → 1`; stops when halted |
| Skeletons | shimmer `linear-gradient` sweep 1.4s linear; off under reduced motion |
| Charts | line draws once on first mount with `stroke-dashoffset` over 480ms; never on data refresh. Crosshair and tooltip follow the pointer with no easing |
| Toasts | in from bottom-right `translateY(8px)`, `--dur-slow`; auto-dismiss 5s; pause on hover/focus |
| Route changes | Next 16 View Transitions (`experimental.viewTransition`): cross-fade `main` at `--dur-base`. Nav and ticket keep their `view-transition-name` so they do not flicker |

---

## 5. Component treatments

**Panel / card.** `e1`, `--r-md`, 1px hairline. Header row: `heading` title left, mono `label` meta right, 16/20px padding, no divider; body begins 4px lower. Clickable cards (Scout): hover raises border to `--border-strong` and adds `e2` shadow over `--dur-fast`; no translate.

**Stat tile.** `label` on top (mono, uppercase, muted), `num-lg` value, optional `num-sm` sub-line in muted. Signed values get color plus sign. Tiles in a row share a single panel with vertical hairlines instead of separate boxes (removes the "box soup" on the trader page).

**Tables.** Header row `--surface-2`, sticky, `label` style. Rows 36px, `num` cells right-aligned, text cells left. Zebra off; hover `--surface-3`; selected row 2px inset left bar in `--accent`. Horizontal overflow: the table scrolls inside its panel with a right-edge fade mask (`mask-image: linear-gradient(90deg, #000 92%, transparent)`) and the first column sticky. Never clip a column silently (today UPNL (ROE) is cut off on Trade). On under 640px, tables with more than 5 columns switch to stacked cards: identifier + PnL on line 1, 2-column key/value grid below.

**Ticket (Trade right rail).** Sticky, own scroll, but the action bar is pinned to the bottom of the rail: preview summary line (`Exposure $217.96 · Margin $13.94 · Liq ~1.5%`) + primary button, always visible. Sections separated by 16px space and a hairline, not by boxes. Amount input: 44px, `num-xl` digits, `$` prefix muted, one focus ring only (today the wrapper and the inner input both draw a ring). Quick-amount pills (25/50/75/Max) are `--r-pill`. The preview block is a quiet `--surface-2` well; warnings inside it use `--warn` text with an icon, not orange body text.

**Sliders.** 4px track `--surface-3`, fill `--accent`; 16px thumb, white, 2px accent border, `e2` shadow; hover/active halo `0 0 0 6px color-mix(accent 20%)`. Tick labels under the track must sit at their real positions (today 1x/10x/25x/50x are spaced evenly on a linear track). Value chip on the right is an editable input. Leverage slider fill switches to `--warn` above 20x and the heat word sits next to the value, not under it.

**Toggles (Switch).** 36x20 track; off `--surface-3`, on `--accent`; thumb white 16px, slides `--dur-base` `--ease-in-out`. Real-money toggles (Trading enabled, Dry run) get a text state next to the switch ("Live" / "Off") so the state is not color-only.

**Segmented control.** Pill track `--surface-2`, sliding thumb `--surface` + `e1` (dark: `--surface-3`), selected text `--fg`, unselected `--muted`. Not filled with accent: the accent is reserved for the primary action, so a screen has one blue block, not six.

**Buttons.** Primary: accent bg, accent-fg text, `--r-pill` (sm/md) or `--r-md` (lg CTA), hover glow. Secondary: `--surface-2` bg, hairline. Ghost: text only. Destructive: outline `--down`. Disabled: 40% opacity plus a tooltip saying why (for example "Enter an amount").

**Badges / chips.** 20px tall, 11px mono uppercase, `--r-pill`, soft bg + matching text. Raw enum keys never render; every flag maps to a human label (see audit).

**Charts.** Hand-rolled SVG stays. Lines 1.5px, area fill gradient from series color at 18% to 0. Grid lines `--faint` at 50% opacity, dashed 2/4. Axis labels `num-sm` muted. "His" series `--fg-soft` thin line; "your copy" `--accent` thicker line (not orange, not green), so the comparison is about shape, not about up/down. Positive/negative area for PnL charts: fill above zero `--up` 14%, below zero `--down` 14%. Crosshair: 1px `--border-strong` vertical line, tooltip `e2`. Daily PnL calendar: diverging 5-step ramp from `--down` through `--surface-3` to `--up`, with legend and per-cell `aria-label`.

**Toasts.** New component (`components/ui/Toast.tsx`, plain React + CSS). Glass `e3`, `--r-md`, icon + one line + optional action. Use for: copy started/updated/stopped, settings saved, errors that today only show inline. `role="status"` (info) or `role="alert"` (error).

**Dialogs.** Glass `e3`, `--r-lg`, max-width 480px, 24px padding. Title `title`, body `body`. Money confirmations show a summary table (wallet, amount, leverage, exposure, liquidation distance) above the buttons; primary confirm on the right; Escape and backdrop cancel; focus starts on Cancel for destructive dialogs.

**Empty states.** Small cat outline (brand at 40%), serif-italic one-word headline, one sentence, one primary action. Never just "No events yet."

**Focus.** 2px `--accent` ring with 2px offset on every interactive element, `:focus-visible` only. Inputs: ring on the wrapper, not the inner `<input>`.

---

## 6. Page layouts

**Global shell.** Sticky glass header 56px: cat + wordmark, primary nav as flat 11px mono uppercase links (`tracking .14em`), active one `--fg` with a 1px accent underline at the header's bottom edge (View Transition name `nav-pill`), right side account switcher, theme, token. A 1px accent scroll-progress hairline runs along the bottom edge (`components/shell/ScrollProgress.tsx`). Mobile (under 640px): header shows cat + account switcher; primary nav moves to a bottom tab bar (5 items, icon + 10px label, 56px + safe-area), Settings into the account switcher menu. Demo mode: a slim `--warn-soft` strip pinned under the header on every page (including Settings and Discover, see audit).

**Trade.** Three columns at 1280px+: Markets 300px, wallet detail flexible, ticket 360px. Bottom dock "Your copies" collapsible, 4 rows visible then scroll. At 1024 to 1279px: Markets collapses to a 56px rail with a search button that opens a drawer. Under 1024px: single column; wallet header, chart, positions, then ticket; the ticket action bar becomes a sticky bottom sheet with the amount and the Copy button. Onboarding strip (1-2-3) shows for first-time real users too, dismissible, remembered per browser.

**Scout.** Header with display title, the sim freshness chip and sub-tabs "Leaderboard / Custom sim" (merges /discover). Filter bar sticky under the header. Card grid `repeat(auto-fill, minmax(320px, 1fr))`, 16px gap. Card: rank + name, tags, PnL + equity, sparkline, Copy Fit bar, one-line "If you copied" result, actions. List view uses the table treatment.

**Trader page (/scout/[address]).** Two-zone layout: left 2/3, right 1/3 sticky. Header card spans full width: identity, tags, account value, Copy Fit, primary "Copy on Trade" (opens Trade with this wallet preselected), secondary "Add to book" only if both are kept (see audit). Left: Performance chart, stat strip (one panel), tabs (Positions, Round trips, Fills, Open orders, Strategy) placed directly under the chart, then Daily PnL calendar. Right: What-if sim, Top coins. Under 1024px: single column, no horizontal scroll.

**Portfolio.** Top: engine status strip (live dot, mode badge, equity, available margin, day PnL, open copies, last cycle). Then "Your copies" table, then Positions, then Event feed with history (last 50 from the api), not live-only. Halt and Close all move into a "Danger zone" menu (kebab) on the status strip, both behind confirm dialogs.

**Account.** Header: label, address chip, `num-xl` account value with signed open PnL. Fund actions (Deposit, Move, Withdraw, Send) shown consistently in real and demo, disabled with a reason when not possible. Equity breakdown bar, then a 3-up stat grid (Overview, Analysis, Performance) as one panel with columns, then chart, then history tabs. Positions tab must include copytrade positions (see audit).

**Settings.** Left sticky section index on desktop (Engine, Sizing, Leverage, Risk limits, Leaders, Display, API). Each section a panel of `SettingRow`s. Real-money rows (Trading enabled, Dry run) live in a top "Live trading" panel with a `--warn-soft` frame and explicit state words. Leverage concepts collapse to one place (see audit H3). New "Display" section: theme, PnL color mode, density (comfortable / compact).

---

## 7. Implementation plan (prioritized)

Each step is a separate PR with gate tests (vitest + jsdom) and screenshots in light/dark at 1440 and 390.

| # | Step | Files | Proof |
|---|---|---|---|
| P0 | Fix the blockers in UX_AUDIT.md first (demo leaking into real Settings/Discover, Day P&L, Account positions). Design work does not start until real-money correctness is green | see audit | regression tests per finding |
| 1 | Tokens: replace `:root` / `.dark` in `globals.css` with section 3 tokens; add `--brand`, `--up`, `--down`, `--warn`, `--surface-3`, `--fg-soft`, `--faint`, radii, motion vars; map old names (`success`→`up`, `danger`→`down`, `warning`→`warn`) as aliases for one release | `src/app/globals.css` | unit test that parses `globals.css` and checks every text/bg token pair against the contrast table (script in this doc's numbers) |
| 2 | Semantic sweep: long/short neutral, status badges off PnL colors, Copy Fit single-hue ramp, accent off numbers | `components/ui/Badge.tsx`, `trade/MarketRow.tsx`, `trade/bits.tsx`, `scout/CopyFitMeter.tsx`, `positions/*` | grep test: no `text-success`/`text-danger` outside PnL helpers |
| 3 | PnL color mode setting + `data-pnl` on `<html>` | `providers.tsx`, `settings/TradeDefaultsPanel.tsx`, `globals.css` | test each mode remaps vars |
| 4 | Primitives: sliding-thumb SegmentedControl and tabs, pill buttons, Switch with state text, single focus ring on inputs, slider ticks at true positions | `components/ui/*` | jsdom tests for keyboard (arrow keys move selection, Home/End) |
| 5 | Ticket: pinned action bar, preview summary line, warnings as `--warn` | `trade/Ticket.tsx`, `trade/PreviewBox.tsx` | test: Copy button in viewport at 1440x800 (Playwright screenshot assertion or layout test) |
| 6 | Shell: nav container width match, glass header, mobile bottom tab bar, demo strip on all pages | `TopNav.tsx`, `layout.tsx` | 390px screenshot, no horizontal scroll (`scrollWidth === clientWidth` check per route) |
| 7 | Motion layer: motion tokens, `@starting-style` panel entrance, value-change flash hook (`useFlashOnChange`), dialog/drawer/popover transitions, View Transitions on routes, reduced-motion overrides | `globals.css`, `hooks/useFlashOnChange.ts`, `ui/Dialog.tsx`, `ui/Drawer.tsx`, `next.config.ts` | test flash throttle (fake timers); reduced-motion snapshot |
| 8 | Toasts | `components/ui/Toast.tsx`, `context/ToastContext.tsx` | tests for queue, dismiss, pause on hover |
| 9 | Charts: series colors, area fills, calendar diverging ramp with `aria-label`s, line draw-in once | `trade/IndexChart.tsx`, `scout/Sparkline.tsx`, `scout/file/PerformanceChart.tsx`, `PnlCalendar.tsx` | snapshot tests on SVG attributes |
| 10 | Page layouts per section 6 (Trader page tabs under chart, Portfolio danger menu, Settings index, Scout sub-tabs) | page components | per-page 1440 / 390 screenshots |
| 11 | Type polish: Instrument Serif display words, mono label style, number styles everywhere | `layout.tsx`, page headers | visual review |

Measurable outcomes to track after shipping: zero raw enum strings in the DOM (gate test), zero routes with horizontal scroll at 390px (gate test), every text token pair at 4.5:1 or better (gate test), primary CTA visible without scrolling on Trade at 1440x800 (gate test), and fewer "what does this mean" questions from the operator on the audited terms.

---

## Sources

- Reference site CSS/markup: https://julianmartinez-delta.vercel.app/
- Hyperliquid design tokens: https://www.webdesignhot.com/design.md/hyperliquid/
- Psychology of color in financial app design: https://windmill.digital/psychology-of-color-in-financial-app-design/
- Color psychology in fintech branding: https://weandthecolor.com/color-psychology-in-fintech-branding-how-the-right-palette-builds-user-trust/209146
- Designing for institutional trust (Perpelio): https://contra.com/p/AQgQkOs2-perpelio-designing-for-institutional-trust
- Visual Finance: the pervasive effects of red on investor behavior: https://pubsonline.informs.org/doi/references/10.1287/mnsc.2020.3747 and SMU Cox summary https://www.smu.edu/cox/coxtoday-magazine/2020-12-09-visual-finance-101
- Importance of colour in trading platforms (Caplin): https://www.caplin.com/insights/posts/2013/11/13/the-importance-of-colour-in-trading-platforms
- Robinhood neon: https://www.ritnerdigital.com/blog/the-psychology-of-ccff00-why-robinhoods-robin-neon-works
- Goodbye red-green scales: https://notes.vis4.net/blog/goodbye-redgreen-scales
- Futubull accessibility (red-green, hollow candles): https://developer.android.com/stories/apps/futu
- Bloomberg on colorblind-accessible terminals: https://www.bloomberg.com/company/?p=20491
- Colorblind palettes (Krzywinski): https://mk.bcgsc.ca/colorblind/img/colorblindness.palettes.v11.pdf
- Red = up in China, Japan, Taiwan: https://www.benzinga.com/general/education/21/10/23258001/did-you-know-you-dont-want-to-be-in-the-green-if-youre-trading-in-china-japan-or-taiwan
- Korea red/blue, i18n discussion: https://lists.w3.org/Archives/Public/www-international/2005JulSep/0188.html
- When red means go: https://behavioraleconomics.com/when-red-means-go
- WCAG contrast for small text: https://developers.google.com/tech-writing/accessibility/self-study/sufficient-contrast and https://ux.pearson.com/prototypes/accessibility-guidelines/patterns/pag/g26
