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

export const SMALL_ACCOUNT_MODES: SmallAccountMode[] = ["concentrate", "bump", "skip"];

/** Allocation fields every Trade wallet carries (LeaderOverride v4/v5). */
export interface AllocationFields {
  allocation_usd?: number | null;
  exposure_mode?: ExposureMode | null;
  target_leverage?: number | null;
  invested_ms?: number | null;
  small_account_mode?: SmallAccountMode | null;
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

/** POST /api/wallets/{address}/copy (and /preview). extra="forbid" server side: never send unknown keys. */
export interface WalletCopyRequest {
  allocation_usd: number;
  exposure_mode: ExposureMode;
  target_leverage?: number;
  margin_mode?: MarginMode;
  max_worse_entry_pct?: number;
  small_account_mode?: SmallAccountMode;
}

/** POST /api/wallets/{address}/stop. */
export interface WalletStopRequest {
  close_positions: boolean;
}

/** One row of GET /api/wallets: our "position" in one wallet. */
export interface WalletPosition {
  address: string;
  allocation_usd: number;
  exposure_mode: ExposureMode;
  target_leverage?: number | null;
  invested_ms?: number | null;
  open_copies: number;
  margin_used_usd: number;
  exposure_usd: number;
  unrealized_pnl_usd: number;
  realized_pnl_usd: number;
  fees_usd: number;
  roe_pct?: number | null;
  stopping: boolean;
  read_ok: boolean;
  equity_usd?: number | null;
  small_account_mode?: SmallAccountMode | null;
}
