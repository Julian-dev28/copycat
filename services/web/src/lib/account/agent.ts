/**
 * Plain-words labels for accounts and their trading agent. Pure.
 *
 * The api sends `agent_status`; the expiry date is the source of truth for
 * the countdown, so a cached "active" whose date has passed reads Expired.
 */
import type { AccountKind, AgentStatus, TradingAccount } from "./types";

export type AgentTone = "success" | "warning" | "danger" | "neutral";

export interface AgentView {
  status: AgentStatus;
  label: string;
  tone: AgentTone;
  daysLeft: number | null;
  /** What to do about it, in plain words; null when nothing is needed. */
  hint: string | null;
}

const DAY = 86_400_000;
/** Mirrors AgentStatus.expiring in the contract: <= 30 days left. */
export const EXPIRING_DAYS = 30;

export function agentView(a: Pick<TradingAccount, "agent_status" | "agent_valid_until_ms" | "kind">, nowMs: number): AgentView {
  const until = a.agent_valid_until_ms ?? null;
  const daysLeft = until === null ? null : Math.max(0, Math.ceil((until - nowMs) / DAY));
  let status = a.agent_status;
  if (until !== null && until <= nowMs && (status === "active" || status === "expiring")) status = "expired";
  if (status === "active" && daysLeft !== null && daysLeft <= EXPIRING_DAYS) status = "expiring";
  const fix = refreshHint(a.kind);

  switch (status) {
    case "active":
      return { status, label: "Active", tone: "success", daysLeft, hint: null };
    case "expiring":
      return {
        status, tone: "warning", daysLeft,
        label: daysLeft === null ? "Expiring" : daysLeft <= 1 ? "Expires today" : `Expires in ${daysLeft}d`,
        hint: `The trading agent stops working when it expires. ${fix}`,
      };
    case "expired":
      return { status, label: "Expired", tone: "danger", daysLeft: 0, hint: `copycat cannot trade this account. ${fix}` };
    case "missing":
      return {
        status, label: "Missing", tone: "danger", daysLeft,
        hint: a.kind === "created"
          ? "No trading agent yet. Hyperliquid only accepts one after the wallet holds funds: deposit, then refresh."
          : `Hyperliquid no longer lists this agent. ${fix}`,
      };
    default:
      return { status: "unknown", label: "Unknown", tone: "neutral", daysLeft, hint: "Could not read the agent from Hyperliquid. Try again shortly." };
  }
}

export function refreshHint(kind: AccountKind): string {
  if (kind === "created") return "Refresh it with your passphrase.";
  if (kind === "connected_signed") return "Refresh it by signing again with your wallet.";
  return "Paste a new API wallet key.";
}

export const KIND_META: Record<AccountKind, { label: string; hint: string }> = {
  created: { label: "Created", hint: "copycat made this wallet. Its key is encrypted with your passphrase on this machine." },
  connected_signed: { label: "Signed", hint: "Your browser wallet approved a trading agent. copycat never saw your main key." },
  connected_key: { label: "API key", hint: "Connected with an API wallet key you created on Hyperliquid." },
};

/** Whether "Refresh agent" makes sense right now (always allowed except while unknown). */
export function canRefresh(v: AgentView): boolean {
  return v.status !== "active" || (v.daysLeft !== null && v.daysLeft <= EXPIRING_DAYS);
}

/** The account the engine trades, or null when none is active (never guessed). */
export function pickActive(accounts: TradingAccount[] | undefined): TradingAccount | null {
  if (!accounts?.length) return null;
  return accounts.find((a) => a.active) ?? null;
}
