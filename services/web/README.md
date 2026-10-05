# copycat web

The copycat UI: Next.js 16 (App Router), React 19, Tailwind 4, TanStack Query.
It talks only to the copycat api (`services/api`); it never calls Hyperliquid
and never holds a trading key beyond a single request.

## Run

```bash
npm ci
NEXT_PUBLIC_COPYCAT_API=http://localhost:8787 npm run dev   # http://localhost:3000
```

Or run the whole stack from the repo root with `make dev` (api, engine, scout,
web) or `docker compose up`. `NEXT_PUBLIC_COPYCAT_API` is baked in at build
time (default `http://localhost:8787`); the api must allow this origin
(`COPYCAT_WEB_ORIGIN`, default `http://localhost:3000`).

First visit: click the key icon in the nav and paste the api token
(`COPYCAT_API_TOKEN` in `.env`, or `cat data/api_token` when the api generated
one). It is kept in `localStorage` only.

## Demo mode

Append `?demo=1` to any page to run it on built-in fixtures with no api: the
Trade book, Scout board and trader files, and the account flows (including a
fake browser wallet that signs with a public test key) all work in memory. On
Trade, `&acct=small` and `&acct=large` switch to a $20 or a $1M account.
On `/account?demo=1`, "Ledger via Rabby" is the fake wallet's own account with
the $0.03 perps / $0.11 spot split (Move to perps shows), "Old API key" is a
unified account, and "Main" is a created wallet (passphrase path, any 12+ chars):
deposit, move, send and withdraw all run against the in-memory store with real
EIP-712 signatures and ERC-20 calldata; a demo deposit is "credited" ~3 s later.

## Pages

| route | what it is |
|---|---|
| `/` (Trade) | Wallets as markets: market list, the wallet's equity index chart, their positions and trades, the invest ticket (global settings or custom: amount, follow or set leverage, margin, small-account mode) with an engine-computed preview, and Your wallets |
| `/scout` | Trader board: Copy Fit score, PnL windows, filters, sorts, presets |
| `/scout/[address]` | Trader file: chart with your simulated copy overlaid, calendar, positions, round trips, fills, orders, what-if, Strategy tab (TA fingerprint + theses) |
| `/portfolio` | Engine status, halt, close all, event feed, your copied wallets |
| `/account` | Active trading account: value, equity split, performance, history tabs; wallet manager (create, connect by wallet signature or API key, switch, refresh agent); funding: Deposit (from Arbitrum through the bridge, from another Hyperliquid account, from an exchange), Move spot <-> perps, Withdraw to Arbitrum, Send between your accounts. Created accounts sign with the passphrase, connected ones with the browser wallet (or app.hyperliquid.xyz when there is none). Flows: `lib/account/depositFlow.ts`, `lib/account/actionFlow.ts`, rules in `lib/account/funding.ts` |
| `/settings` | Global settings every "global" wallet follows: enabled, dry run, sizing, leverage, risk limits |
| `/discover` | Custom discovery sim runs (linked from Scout) |

`/copy`, `/positions` and `/trade` redirect to their current homes and keep the
query string.

## Layout

```
src/app/          routes (one folder per page)
src/components/   UI by area: trade/, scout/, account/, copy/ (settings panels),
                  positions/, discover/, ui/ (shared primitives), TopNav, CatLogo
src/lib/          pure logic + tests by area: trade/, scout/, account/, api/
src/hooks/        TanStack Query hooks and small React hooks
src/context/      AuthContext (api token)
```

Logic lives in `src/lib` as plain functions with vitest tests next to them;
components stay thin. API types come from the api's OpenAPI schema:
`npm run gen:api` regenerates `src/lib/api/schema.gen.ts` from
`../api/openapi.json` (run `make openapi` at the repo root after a contract
change). `src/lib/api/types.ts` holds the hand-kept constants (contract
version, limits).

## Gate

All four must pass before a commit (CI runs the same):

```bash
npm run lint        # eslint, --max-warnings 0
npm run typecheck   # tsc --noEmit
npm test            # vitest
npm run build       # next build
```

Lint uses the React Compiler rules: no `setState` inside `useEffect` and no
ref writes during render. Sync a draft from server data with
`src/hooks/useSyncedState.ts` (adjust-during-render) and read browser state
with `useSyncExternalStore`.

## Security rules for UI code

- Secrets (a created wallet's private key, passphrases, an agent key during
  sign-in) live only in component state for the one request, never in
  `localStorage`, the query cache or logs, and are cleared when the dialog
  closes.
- Trader theses render through `SafeMarkdown` (react-markdown without raw HTML;
  only http(s), mailto and relative links; no images).
- Turning trading live (enabled and not dry run) always goes through a confirm
  dialog, from any switch or ticket that would cause it.
