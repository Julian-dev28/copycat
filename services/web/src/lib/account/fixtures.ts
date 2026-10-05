/**
 * Deterministic demo data for the Account page and wallet manager
 * (`?demo=1`). Funded accounts borrow a Scout trader file for their curves,
 * positions and fills (same fixtures the Scout pages use), so every chart
 * and tab has something real-looking in it. A freshly created demo wallet
 * is empty, which is what the fund panel is for.
 */
import { demoFileRow } from "@/lib/scout/file/fixtures";
import { fixtureOrders, fixtureProfile } from "@/lib/scout/fixtures";
import type { TraderProfile } from "@/lib/scout/types";
import type { AccountSummary, HistoryKind, TradingAccount } from "./types";

import { DEMO_WALLET_ADDRESS } from "./demoWallet";

export { DEMO_WALLET_ADDRESS, DEMO_WALLET_MODES, fakeWalletProvider, type DemoWalletMode } from "./demoWallet";

const DAY = 86_400_000;

export function fixtureAccounts(nowMs: number): TradingAccount[] {
  return [
    {
      id: "acc_main", label: "Main", kind: "created", address: "0x7a3f2c19e04b8d5a6c1e9f20b3d4a5c6e7f80911",
      agent_address: "0x9c0ffee000000000000000000000000000c47a91", agent_name: "copycat",
      agent_valid_until_ms: nowMs + 142 * DAY, agent_status: "active", active: true, created_ms: nowMs - 60 * DAY, has_main_key: true,
    },
    {
      id: "acc_ledger", label: "Ledger via Rabby", kind: "connected_signed", address: DEMO_WALLET_ADDRESS, // the demo browser wallet owns it
      agent_address: "0x4a6e000000000000000000000000000000d0c0a7", agent_name: "copycat",
      agent_valid_until_ms: nowMs + 12 * DAY, agent_status: "expiring", active: false, created_ms: nowMs - 170 * DAY, has_main_key: false,
    },
    {
      id: "acc_api", label: "Old API key", kind: "connected_key", address: "0xe5c4b3a2918070f6e5d4c3b2a19080706f5e4d3c",
      agent_address: "0x1d1e000000000000000000000000000000ba5eba", agent_name: null,
      agent_valid_until_ms: nowMs - 3 * DAY, agent_status: "expired", active: false, created_ms: nowMs - 400 * DAY, has_main_key: false,
    },
  ];
}

function profileFor(address: string, nowMs: number): TraderProfile {
  return fixtureProfile(demoFileRow(address, nowMs), nowMs);
}

export function emptySummary(account: TradingAccount, nowMs: number): AccountSummary {
  return {
    account,
    balances: { perps_usd: 0, spot_usd: 0, staked_usd: 0, copytrade_usd: 0, total_usd: 0, withdrawable_usd: 0 },
    unrealized_pnl_usd: 0, account_leverage: 0, margin_usage_pct: 0, all_time_pnl_usd: null, volume_usd: null,
    long_notional_usd: 0, short_notional_usd: 0, pnl_curve: {}, value_curve: {}, daily_pnl: [], as_of_ms: nowMs,
  };
}

/** `funded` false = a wallet created this session that nobody has deposited to. */
export function fixtureSummary(account: TradingAccount, nowMs: number, funded = true): AccountSummary {
  if (!funded) return emptySummary(account, nowMs);
  const p = profileFor(account.address, nowMs);
  const { account: risk, row } = p;
  const total = risk.perps_usd + risk.spot_usd + risk.staked_usd;
  const allTime = row.perf.find((x) => x.window === "all");
  return {
    account,
    balances: {
      perps_usd: risk.perps_usd, spot_usd: risk.spot_usd, staked_usd: risk.staked_usd,
      copytrade_usd: account.active ? Math.round(risk.perps_usd * 0.35) : 0,
      total_usd: total, withdrawable_usd: Math.max(0, Math.round(risk.perps_usd * (1 - risk.margin_usage_pct / 100))),
    },
    unrealized_pnl_usd: risk.unrealized_pnl_usd, account_leverage: risk.account_leverage, margin_usage_pct: risk.margin_usage_pct,
    all_time_pnl_usd: allTime?.pnl_usd ?? null, volume_usd: allTime?.volume_usd ?? null,
    longest_win_streak_days: p.longest_win_streak_days, style: row.style ?? null,
    avg_hold_h: row.trades_30d.avg_hold_h ?? null, median_hold_h: row.trades_30d.median_hold_h ?? null,
    pnl_tier: row.pnl_tier, size_tier: row.size_tier, risk_30d: row.risk_30d, trades_30d: row.trades_30d,
    long_notional_usd: risk.long_notional_usd, short_notional_usd: risk.short_notional_usd,
    pnl_curve: p.pnl_curve, value_curve: p.value_curve, daily_pnl: p.daily_pnl, as_of_ms: nowMs,
  };
}

function transfers(account: TradingAccount, nowMs: number) {
  const a = account.address;
  return [
    { time: nowMs - 2 * DAY, hash: "0xd1", delta: { type: "deposit", usdc: "2500.0" } },
    { time: nowMs - 5 * DAY, hash: "0xd2", delta: { type: "accountClassTransfer", usdc: "400.0", toPerp: false } },
    { time: nowMs - 9 * DAY, hash: "0xd3", delta: { type: "send", usdc: "150.0", user: a, destination: DEMO_WALLET_ADDRESS } },
    { time: nowMs - 20 * DAY, hash: "0xd4", delta: { type: "withdraw", usdc: "1200.0", fee: "1.0" } },
    { time: nowMs - 41 * DAY, hash: "0xd5", delta: { type: "deposit", usdc: "10000.0" } },
  ];
}

/** Raw-ish rows, the way HL's info endpoints shape them, so the normalizers get exercised in demo too. */
export function fixtureHistory(account: TradingAccount, kind: HistoryKind, nowMs: number, funded = true): unknown {
  if (!funded) return [];
  const p = profileFor(account.address, nowMs);
  switch (kind) {
    case "fills":
      return p.recent_fills;
    case "orders":
      return fixtureOrders(demoFileRow(account.address, nowMs), nowMs).map((o, i) => ({
        ...o, status: i % 3 === 1 ? "filled" : i % 3 === 2 ? "canceled" : "open", status_ms: o.time_ms + i * 60_000,
      }));
    case "transfers":
      return transfers(account, nowMs);
    case "balances":
      return [
        { coin: "USDC", total: String(p.account.spot_usd), hold: "0" },
        { coin: "HYPE", total: "42.5", hold: "0", usd_value: 42.5 * 38.2 },
        { coin: "PURR", total: "12000", hold: "2000", usd_value: 12000 * 0.21 },
      ];
  }
}
