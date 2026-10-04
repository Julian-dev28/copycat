/**
 * GET /api/accounts/{id}/history?kind=... -> display rows. Reads the
 * contract shapes (snake_case) and Hyperliquid's raw info rows, so the
 * tabs keep working whichever the api passes through. Rows that lack the
 * fields a table needs are dropped, never rendered as NaN. Pure.
 */
import { normalizeOrders, type OpenOrderView } from "@/lib/scout/labels";
import type { LeaderFillView } from "@/lib/scout/types";
import type { BalanceRow, HistoryKind, TransferRow } from "./types";

type Rec = Record<string, unknown>;

function rows(raw: unknown): Rec[] {
  const arr = Array.isArray(raw) ? raw : raw && typeof raw === "object" ? ((raw as Rec).rows ?? (raw as Rec).items) : null;
  return Array.isArray(arr) ? arr.filter((r): r is Rec => Boolean(r) && typeof r === "object") : [];
}

function num(v: unknown): number | null {
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isFinite(x) ? x : null;
}

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

export function normalizeFills(raw: unknown): LeaderFillView[] {
  const out: LeaderFillView[] = [];
  for (const r of rows(raw)) {
    const time = num(r.time_ms ?? r.time);
    const px = num(r.px);
    const sz = num(r.sz);
    const coin = str(r.coin);
    if (time === null || px === null || sz === null || !coin || (r.side !== "B" && r.side !== "A")) continue;
    out.push({
      time_ms: time, coin, side: r.side, dir: str(r.dir) ?? (r.side === "B" ? "Buy" : "Sell"), px, sz,
      notional_usd: num(r.notional_usd) ?? px * sz,
      closed_pnl_usd: num(r.closed_pnl_usd ?? r.closedPnl) ?? 0,
      fee_usd: num(r.fee_usd ?? r.fee) ?? 0,
    });
  }
  return out.sort((a, b) => b.time_ms - a.time_ms);
}

export function normalizeOrderRows(raw: unknown): OpenOrderView[] {
  return normalizeOrders(rows(raw));
}

const TRANSFER_LABEL: Record<string, string> = {
  deposit: "Deposit", withdraw: "Withdrawal", send: "Send", usdSend: "Send", spotTransfer: "Spot transfer",
  accountClassTransfer: "Perps ⇄ spot", internalTransfer: "Internal transfer", subAccountTransfer: "Sub-account",
  vaultDeposit: "Vault deposit", vaultWithdraw: "Vault withdrawal", liquidation: "Liquidation", rewardsClaim: "Rewards",
};

export function transferLabel(type: string): string {
  return TRANSFER_LABEL[type] ?? type.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase());
}

/** `self` is this account's address: sends from it are "out", to it "in". */
export function normalizeTransfers(raw: unknown, self: string): TransferRow[] {
  const me = self.toLowerCase();
  const out: TransferRow[] = [];
  for (const r of rows(raw)) {
    const d = (r.delta && typeof r.delta === "object" ? r.delta : r) as Rec;
    const time = num(r.time_ms ?? r.time);
    const type = str(d.type) ?? str(r.type);
    const amount = num(r.amount_usd ?? d.usdc ?? d.usdcValue ?? d.amount);
    if (time === null || !type || amount === null) continue;
    const from = str(d.user)?.toLowerCase() ?? null;
    const to = str(d.destination)?.toLowerCase() ?? null;
    let direction: TransferRow["direction"] = r.direction === "in" || r.direction === "out" || r.direction === "internal" ? r.direction : "internal";
    if (!r.direction) {
      if (type === "deposit" || (to === me && from !== me)) direction = "in";
      else if (type === "withdraw" || (from === me && to !== me && to)) direction = "out";
      else if (amount < 0) direction = "out";
    }
    const counterparty = str(r.counterparty) ?? (direction === "out" ? to : direction === "in" ? from : null);
    out.push({ time_ms: time, type, amount_usd: Math.abs(amount), direction, counterparty: counterparty === me ? null : counterparty, hash: str(r.hash) });
  }
  return out.sort((a, b) => b.time_ms - a.time_ms);
}

export function normalizeBalances(raw: unknown): BalanceRow[] {
  const out: BalanceRow[] = [];
  for (const r of rows(raw)) {
    const coin = str(r.coin) ?? str(r.token);
    const total = num(r.total);
    if (!coin || total === null) continue;
    const hold = num(r.hold) ?? 0;
    const usd = num(r.usd_value ?? r.usdValue) ?? (coin === "USDC" ? total : null);
    out.push({ coin, total, hold, usd_value: usd });
  }
  return out.filter((b) => b.total !== 0 || b.hold !== 0).sort((a, b) => (b.usd_value ?? -1) - (a.usd_value ?? -1));
}

export const HISTORY_KINDS: HistoryKind[] = ["fills", "orders", "transfers", "balances"];
