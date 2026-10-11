/**
 * Trade page (contract v4/v5) wire types, mirrored by hand from
 * contracts/models.py ("Trade page" section, SmallAccountMode, the wallet
 * routes) so this page does not depend on when schema.gen.ts is regenerated.
 * When `npm run gen:api` carries these, swap the aliases for Schemas[...];
 * the rest of the Trade code imports from this file only.
 *
 * Units follow the contract: USD, percent as percent, leverage as int x, epoch ms.
 */
import type { EngineStatus, LeaderOverride, LeaderStatus, Settings } from "@/lib/api/types";

export type ExposureMode = "match" | "target";
export type SmallAccountMode = "concentrate" | "bump" | "skip";
export type MarginMode = "isolated" | "cross";
export type LeverageMode = "max" | "match" | "fixed";
/** v7: copy a wallet with the Settings tab as-is, or with its own terms. */
export type SettingsSource = "global" | "custom";
/** v8: copy mirrors his sides; counter takes the opposite side of every position he opens. */
export type TradeDirection = "copy" | "counter";
/** v8: a wallet's lifecycle. paused = no new opens/adds, exits still mirrored. */
export type WalletStatus = "running" | "paused" | "stopping" | "stopped" | "archived";

export const SMALL_ACCOUNT_MODES: SmallAccountMode[] = ["concentrate", "bump", "skip"];

/** Allocation fields every Trade wallet carries (LeaderOverride v4/v5). */
export interface AllocationFields {
  allocation_usd?: number | null;
  exposure_mode?: ExposureMode | null;
  target_leverage?: number | null;
  invested_ms?: number | null;
  small_account_mode?: SmallAccountMode | null;
  only_new_positions?: boolean | null;
  /** v8 */
  trade_direction?: TradeDirection | null;
  coin_allowlist?: string[] | null;
  coin_blocklist?: string[] | null;
  paused?: boolean | null;
}

export type TradeOverride = Omit<LeaderOverride, "sizing_mode"> & AllocationFields & {
  sizing_mode?: LeaderOverride["sizing_mode"] | "allocation" | null;
};

/** Settings as the v5 api returns it. Older apis omit the v4/v5 fields, so they are optional here. */
export type TradeSettings = Omit<Settings, "leader_overrides" | "sizing_mode"> & {
  sizing_mode: Settings["sizing_mode"] | "allocation";
  leader_overrides: Record<string, TradeOverride>;
  allocation_usd?: number;
  exposure_mode?: ExposureMode;
  target_leverage?: number;
  small_account_mode?: SmallAccountMode;
  max_order_volume_pct?: number;
  max_slippage_pct?: number;
  /** v8 book-wide defaults (older apis omit them). */
  trade_direction?: TradeDirection;
  coin_allowlist?: string[];
  coin_blocklist?: string[];
  paused?: boolean;
};

/** LeaderStatus with the v4 per-wallet position fields. */
export type TradeLeaderStatus = LeaderStatus & {
  open_copies?: number;
  margin_used_usd?: number;
  exposure_usd?: number;
  unrealized_pnl_usd?: number;
  realized_pnl_usd?: number;
  fees_usd?: number;
  stopping?: boolean;
};

export type TradeStatus = Omit<EngineStatus, "leaders"> & { leaders: TradeLeaderStatus[] };

/**
 * POST /api/wallets/{address}/copy (and /preview), contract v7. extra="forbid"
 * server side: never send unknown keys (a pre-v7 api rejects settings_source).
 * global: the Settings tab as-is, other fields ignored. custom: allocation_usd
 * required; anything unset still inherits from Settings.
 */
export interface WalletCopyRequest {
  settings_source?: SettingsSource;
  allocation_usd?: number;
  exposure_mode?: ExposureMode;
  target_leverage?: number;
  margin_mode?: MarginMode;
  max_worse_entry_pct?: number;
  small_account_mode?: SmallAccountMode;
  leverage_mode?: LeverageMode;
  leverage?: number;
  only_new_positions?: boolean;
  /** v8, custom only. Never sent to a pre-v8 api (extra="forbid"). */
  trade_direction?: TradeDirection;
  coin_allowlist?: string[];
  coin_blocklist?: string[];
}

/** POST /api/wallets/{address}/stop. */
export interface WalletStopRequest {
  close_positions: boolean;
}

/** One row of GET /api/wallets (contract WalletPosition): our "position" in one wallet. */
export interface WalletPosition {
  address: string;
  /** False: stopped, copies winding down. Older apis omit it (treated as true). */
  in_book?: boolean;
  read_ok: boolean;
  equity_usd?: number | null;
  open_copies: number;
  margin_used_usd: number;
  exposure_usd: number;
  unrealized_pnl_usd: number;
  realized_pnl_usd: number;
  fees_usd: number;
  pnl_usd?: number;
  roe_pct?: number | null;
  stopping: boolean;
  owned_coins?: string[];
  last_read_ms?: number | null;
  sizing_mode?: string | null;
  allocation_usd?: number | null;
  exposure_mode?: ExposureMode | null;
  target_leverage?: number | null;
  small_account_mode?: SmallAccountMode | null;
  invested_ms?: number | null;
  /** v7: which terms this wallet copies with. Older apis omit it. */
  settings_source?: SettingsSource | null;
  /** v8. Older apis omit these; lib/trade/lifecycle.ts derives the status. */
  status?: WalletStatus | null;
  trade_direction?: TradeDirection | null;
  coin_allowlist?: string[] | null;
  coin_blocklist?: string[] | null;
  style?: TradingStyleName | null;
  archived_ms?: number | null;
}

export type TradingStyleName = "algo" | "scalp" | "intraday" | "swing" | "position";

/** GET /api/wallets/{a}/projection (contract WalletProjection). */
export interface WalletProjection {
  address: string;
  allocation_usd: number;
  trade_direction: TradeDirection;
  curve: { t_ms: number; value: number }[];
  return_pct: number;
  max_drawdown_pct: number;
  liquidations: number;
  copies: number;
  skipped: number;
  note?: string | null;
}

/** Query for the projection route. */
export interface ProjectionQuery {
  allocation_usd: number;
  trade_direction: TradeDirection;
  exposure_mode: ExposureMode;
  target_leverage?: number;
}
