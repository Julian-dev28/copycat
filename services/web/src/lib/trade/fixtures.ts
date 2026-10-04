/**
 * `?demo=1` Trade fixtures: three account sizes, deterministic market data,
 * and an in-memory book that Copy / Update / Stop really change, so the
 * whole flow runs with no api. `&acct=small` is a $20 account (every slice
 * near the $10.50 minimum), `&acct=large` a $1M one (liquidity caps bite),
 * the default is $1,000. Same clock + same actions = same numbers.
 */
import { normAddr } from "@/lib/address";
import type { CopyPosition } from "@/lib/api/types";
import { demoFileRow } from "@/lib/scout/file/fixtures";
import { fixtureProfile } from "@/lib/scout/fixtures";
import type { TraderPositionView } from "@/lib/scout/types";
import { localPreview } from "./preview";
import type {
  ExposureMode, MarginMode, SettingsSource, SmallAccountMode, TradeLeaderStatus, TradeOverride, TradeSettings, TradeStatus, WalletCopyRequest,
  WalletPosition,
} from "./types";

export type DemoAccount = "small" | "default" | "large";
export const DEMO_EQUITY: Record<DemoAccount, number> = { small: 20, default: 1_000, large: 1_000_000 };

export function demoAccount(param: string | null | undefined): DemoAccount {
  return param === "small" || param === "large" ? param : "default";
}

/** 24h volume per coin, USD, for the liquidity cap preview (order of magnitude of real HL books). */
export const VOLUME_24H: Record<string, number> = {
  BTC: 2.4e9, ETH: 1.3e9, SOL: 4.2e8, HYPE: 3.1e8, kPEPE: 3.8e7, DOGE: 1.4e8, SUI: 8.2e7, AVAX: 5.9e7, LINK: 4.6e7,
  ENA: 6.1e7, FARTCOIN: 2.7e7, "xyz:TSLA": 1.9e7, "xyz:NVDA": 1.4e7, "xyz:XYZ100": 2.9e7, "xyz:GOLD": 9.5e6,
};

/** The Settings tab's per-wallet budget in each demo account, used by "Use global" wallets. */
export const DEMO_GLOBAL_ALLOCATION: Record<DemoAccount, number> = { small: 10, default: 100, large: 100_000 };

export function demoSettings(acct: DemoAccount = "default"): TradeSettings {
  return {
    contract_version: 7, enabled: true, dry_run: true, leaders: [], sizing_mode: "allocation", fixed_margin_usd: 5,
    fixed_notional_usd: 10.5, size_multiplier: 1, sleeve_frac: 1, leverage_mode: "match", leverage: 20, max_position_leverage: 50,
    margin_mode: "isolated", include_spot_staked: false, only_new_positions: false, max_worse_entry_pct: 10, min_order_bump: true,
    daily_loss_limit_usd: 0, max_open_copies: 10, poll_interval_s: 5, leader_overrides: {}, allocation_usd: DEMO_GLOBAL_ALLOCATION[acct],
    exposure_mode: "match", target_leverage: 5, small_account_mode: "concentrate", max_order_volume_pct: 0.5, max_slippage_pct: 1,
  };
}

export function leaderPositions(address: string, nowMs: number): { equity: number; positions: TraderPositionView[] } {
  const p = fixtureProfile(demoFileRow(address, nowMs), nowMs);
  return { equity: p.row.account_value_usd, positions: p.positions };
}

export interface WalletTerms {
  source: SettingsSource;
  allocationUsd: number;
  mode: ExposureMode;
  targetLeverage: number;
  marginMode: MarginMode;
  smallMode: SmallAccountMode;
  onlyNew: boolean;
}

/** The terms a wallet copies with: its override over the Settings tab (custom), or the tab as-is (global). */
export function walletTerms(s: TradeSettings, address: string, body?: WalletCopyRequest): WalletTerms {
  const a = normAddr(address);
  const custom = body ? body.settings_source !== "global" : Boolean(s.leader_overrides[a]?.allocation_usd);
  const o: TradeOverride = custom ? ((body as TradeOverride | undefined) ?? s.leader_overrides[a] ?? {}) : {};
  return {
    source: custom ? "custom" : "global",
    allocationUsd: o.allocation_usd ?? s.allocation_usd ?? 0,
    mode: o.exposure_mode ?? s.exposure_mode ?? "match",
    targetLeverage: o.target_leverage ?? s.target_leverage ?? 5,
    marginMode: o.margin_mode ?? s.margin_mode,
    smallMode: o.small_account_mode ?? s.small_account_mode ?? "concentrate",
    onlyNew: o.only_new_positions ?? s.only_new_positions,
  };
}

/** Our copies of one wallet, as the engine would hold them right after copying. */
export function demoWallet(address: string, s: TradeSettings, nowMs: number, stopping: boolean, equityUsd: number): { wallet: WalletPosition; copies: CopyPosition[] } {
  const a = normAddr(address);
  const o = s.leader_overrides[a] ?? {};
  const t = walletTerms(s, a);
  const { equity, positions: his } = leaderPositions(a, nowMs);
  // Only new positions: nothing he holds at copy time is mirrored.
  const positions = t.onlyNew ? [] : his;
  const alloc = t.allocationUsd;
  const pv = localPreview({
    allocationUsd: alloc, mode: t.mode, targetLeverage: t.targetLeverage, marginMode: t.marginMode, smallMode: t.smallMode,
    leaderEquityUsd: equity, positions, volume24hUsd: VOLUME_24H, maxOrderVolumePct: s.max_order_volume_pct, ourEquityUsd: equityUsd,
  });
  const invested = o.invested_ms ?? nowMs;
  const hours = Math.max(0, (nowMs - invested) / 3_600_000);
  const copies: CopyPosition[] = [];
  let upnl = 0;
  pv.copies.forEach((c, i) => {
    if (c.status === "skipped") return;
    const his = positions[i];
    const ratio = c.notionalUsd / Math.max(1, his.notional_usd);
    const u = his.unrealized_pnl_usd * ratio * 0.35; // we entered later than him: a slice of his move
    upnl += u;
    const size = (c.notionalUsd / his.mark_px) * (c.side === "long" ? 1 : -1);
    copies.push({
      coin: c.coin, leader: a, side: c.side, size, entry_px: his.mark_px * (c.side === "long" ? 0.998 : 1.002), mark_px: his.mark_px,
      notional_usd: c.notionalUsd, leverage: c.leverage, is_cross: t.marginMode === "cross", unrealized_pnl_usd: u,
      liquidation_px: null, opened_ms: invested, sizing_mode: "fixed_notional",
    });
  });
  const realized = alloc * 0.0006 * Math.min(48, hours);
  const fees = pv.exposureUsd * 0.00045;
  return {
    copies,
    wallet: {
      address: a, allocation_usd: alloc, exposure_mode: t.mode, target_leverage: t.mode === "target" ? t.targetLeverage : null, settings_source: t.source,
      invested_ms: invested, open_copies: copies.length, margin_used_usd: pv.marginUsd, exposure_usd: pv.exposureUsd,
      unrealized_pnl_usd: upnl, realized_pnl_usd: realized, fees_usd: fees,
      roe_pct: alloc > 0 ? ((upnl + realized - fees) / alloc) * 100 : null, stopping, read_ok: true, equity_usd: equity,
      small_account_mode: t.smallMode,
    },
  };
}

export function demoStatus(s: TradeSettings, acct: DemoAccount, nowMs: number, stopping: Set<string>): { status: TradeStatus; wallets: WalletPosition[] } {
  const base = DEMO_EQUITY[acct];
  const built = s.leaders.map((a) => demoWallet(a, s, nowMs, stopping.has(a), base));
  const wallets = built.map((b) => b.wallet);
  const pnl = wallets.reduce((x, w) => x + w.unrealized_pnl_usd + w.realized_pnl_usd - w.fees_usd, 0);
  const equity = base + pnl;
  const used = wallets.reduce((x, w) => x + w.margin_used_usd, 0);
  const leaders: TradeLeaderStatus[] = wallets.map((w) => ({
    address: w.address, read_ok: true, equity_usd: w.equity_usd, open_positions: w.open_copies, owned_coins: [], last_read_ms: nowMs - 3_000,
    effective: s as unknown as TradeLeaderStatus["effective"], open_copies: w.open_copies, margin_used_usd: w.margin_used_usd,
    exposure_usd: w.exposure_usd, unrealized_pnl_usd: w.unrealized_pnl_usd, realized_pnl_usd: w.realized_pnl_usd, fees_usd: w.fees_usd,
    stopping: w.stopping,
  }));
  return {
    wallets,
    status: {
      running: true, enabled: s.enabled, dry_run: s.dry_run, last_cycle_ms: nowMs - 2_000, cycle_ms: 410,
      our_address: "0x0000000000000000000000000000000000c0ffee", equity_usd: equity,
      available_margin_usd: Math.max(0, equity - used), day_pnl_usd: pnl, halted_reason: null,
      positions: built.flatMap((b) => b.copies), leaders,
    },
  };
}
