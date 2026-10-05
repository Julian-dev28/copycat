/**
 * Trading accounts (contract v6) wire types, mirrored by hand from
 * contracts/models.py ("Trading accounts (v6)") until services/api ships the
 * routes and `npm run gen:api` regenerates schema.gen.ts. When that lands,
 * swap each alias here for `Schemas["..."]`; the rest of the app imports
 * from this file only.
 *
 * Units follow the contract: USD, percent as percent, epoch ms.
 * Nothing in here ever carries a secret except the three request/response
 * shapes marked SECRET, which must never be cached, logged or persisted.
 */
import type { CurvePoint, PnlTier, PnlWindow, RiskStats, SizeTier, TradeStats, TradingStyle } from "@/lib/scout/types";

export type AccountKind = "created" | "connected_signed" | "connected_key";
export type AgentStatus = "active" | "expiring" | "expired" | "missing" | "unknown";

export interface TradingAccount {
  id: string;
  label: string;
  kind: AccountKind;
  address: string;
  agent_address?: string | null;
  agent_name?: string | null;
  agent_valid_until_ms?: number | null;
  agent_status: AgentStatus;
  active: boolean;
  created_ms: number;
  has_main_key: boolean;
}

export interface AccountBalances {
  perps_usd: number;
  spot_usd: number;
  staked_usd: number;
  copytrade_usd: number;
  total_usd: number;
  withdrawable_usd: number;
}

export interface CreateAccountRequest {
  label: string;
  /** SECRET */
  passphrase: string;
}

/** SECRET: private_key is shown once, then dropped from memory. */
export interface CreateAccountResponse {
  account: TradingAccount;
  private_key: string;
  backup_warning: string;
}

export interface ImportApiKeyRequest {
  label: string;
  main_address: string;
  /** SECRET */
  agent_private_key: string;
}

export interface AgentApprovalPrepareRequest {
  main_address: string;
  agent_address: string;
  agent_name?: string;
}

export interface AgentApprovalPrepareResponse {
  typed_data: Record<string, unknown>;
  action: Record<string, unknown>;
  nonce: number;
}

export interface AgentApprovalSubmitRequest {
  label: string;
  main_address: string;
  /** SECRET: generated in the browser for this one request. */
  agent_private_key: string;
  action: Record<string, unknown>;
  nonce: number;
  signature: string;
}

export interface TransferRequest {
  from_account_id: string;
  to_address: string;
  amount_usd: number;
  /** SECRET */
  passphrase: string;
}

export interface AccountSummary {
  account: TradingAccount;
  balances: AccountBalances;
  unrealized_pnl_usd: number;
  account_leverage: number;
  margin_usage_pct: number;
  all_time_pnl_usd?: number | null;
  volume_usd?: number | null;
  longest_win_streak_days?: number | null;
  style?: TradingStyle | null;
  avg_hold_h?: number | null;
  median_hold_h?: number | null;
  pnl_tier?: PnlTier | null;
  size_tier?: SizeTier | null;
  risk_30d?: RiskStats | null;
  trades_30d?: TradeStats | null;
  long_notional_usd: number;
  short_notional_usd: number;
  pnl_curve: Partial<Record<PnlWindow, CurvePoint[]>>;
  value_curve: Partial<Record<PnlWindow, CurvePoint[]>>;
  daily_pnl: CurvePoint[];
  as_of_ms: number;
}

/** GET /api/accounts/import-env: whether the one-click .env migration applies. */
export interface ImportEnvStatus {
  available: boolean;
  address?: string | null;
  reason?: string | null;
}

export type HistoryKind = "fills" | "orders" | "transfers" | "balances";

/** One ledger movement (deposit, withdrawal, send, spot/perp move). */
export interface TransferRow {
  time_ms: number;
  type: string;
  amount_usd: number;
  /** Signed from this account's point of view: + in, - out. */
  direction: "in" | "out" | "internal";
  counterparty: string | null;
  hash: string | null;
}

/** One spot/perp balance line. */
export interface BalanceRow {
  coin: string;
  total: number;
  hold: number;
  usd_value: number | null;
}

// ── Funding (contract v8) ─────────────────────────────────────────────────────

export type UserActionKind = "usd_class_transfer" | "usd_send" | "withdraw";

/** Live maxima, read from Hyperliquid by GET .../funding-info. */
export interface FundingLimits {
  abstraction?: string | null;
  /** Spot and perps share one USDC balance: no spot/perps move needed. */
  unified: boolean;
  /** usdSend / withdraw3 / perps -> spot */
  perps_withdrawable_usd: number;
  /** spot -> perps */
  spot_usdc_free_usd: number;
}

/** GET /api/accounts/{id}/funding-info */
export interface FundingInfo {
  network: "mainnet" | "testnet";
  chain_id: number;
  chain_name: string;
  usdc_address: string;
  bridge_address: string;
  explorer_url: string;
  min_deposit_usd: number;
  withdraw_fee_usd: number;
  account_address: string;
  account_kind: AccountKind;
  signer: "browser" | "passphrase";
  limits?: FundingLimits | null;
  source_url: string;
  notes: string[];
}

export interface UserActionPrepareRequest {
  kind: UserActionKind;
  amount_usd: number;
  to_perp?: boolean | null;
  destination?: string | null;
  confirm_destination?: string | null;
}

export interface UserActionPrepareResponse {
  typed_data: Record<string, unknown>;
  action: Record<string, unknown>;
  nonce: number;
}

export interface UserActionSubmitRequest {
  kind: UserActionKind;
  action: Record<string, unknown>;
  nonce: number;
  signature: string;
  confirm_destination?: string | null;
}

export interface UserActionRunRequest extends UserActionPrepareRequest {
  /** SECRET */
  passphrase: string;
}

export interface UserActionResult {
  ok: boolean;
  kind: UserActionKind;
  account_address: string;
  amount_usd: number;
  to_perp?: boolean | null;
  destination?: string | null;
  fee_usd?: number | null;
  nonce: number;
  message: string;
}
