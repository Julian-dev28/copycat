"use client";

import { ExternalLink, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { qrPath } from "@/lib/account/qr";
import type { TradingAccount } from "@/lib/account/types";
import { CopyButton } from "./bits";

/** Black on white whatever the theme: phone cameras read dark-on-light codes most reliably. */
export function QrCode({ text, size = 168 }: { text: string; size?: number }) {
  const qr = qrPath(text);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${qr.size} ${qr.size}`} role="img" aria-label={`QR code for ${text}`} shapeRendering="crispEdges" className="rounded-lg">
      <rect width={qr.size} height={qr.size} fill="#ffffff" />
      <path d={qr.d} fill="#0b0b0a" />
    </svg>
  );
}

/** Exported so a test can pin the facts in this copy without rendering JSX. */
export const STEPS = [
  "From another Hyperliquid account: Send USDC (perps balance) to this address. It lands in seconds, no gas.",
  "From an exchange: withdraw USDC on the Hyperliquid network (not Arbitrum) to this address.",
  "From Arbitrum: Hyperliquid credits whichever address sends the USDC, not whatever address you paste. Click Deposit for the full flow and its guardrails (minimum 5 USDC). A plain Arbitrum transfer to this address outside that flow just sits there, uncredited.",
  "When the balance shows up, refresh the trading agent. Hyperliquid only accepts an agent for a funded account.",
];

export function FundPanel({
  account, onRefreshAgent, refreshing, needsAgent,
}: {
  account: TradingAccount;
  onRefreshAgent?: () => void;
  refreshing?: boolean;
  needsAgent: boolean;
}) {
  return (
    <section aria-label="Fund this wallet" className="flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-semibold">Fund this wallet</h3>
        <p className="mt-0.5 text-xs text-muted">copycat trades with what sits in this account. Deposit USDC to start.</p>
      </div>
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        <div className="flex flex-col items-center gap-2">
          <QrCode text={account.address} />
          <CopyButton text={account.address} label="Copy address" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-muted">Deposit address</p>
          <p className="font-num text-xs break-all text-foreground">{account.address}</p>
          <ol className="mt-3 flex list-decimal flex-col gap-1.5 pl-4 text-xs text-muted">
            {STEPS.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <a
            href="https://app.hyperliquid.xyz/portfolio"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
          >
            Open Hyperliquid <ExternalLink size={12} aria-hidden="true" />
          </a>
        </div>
      </div>
      {needsAgent && onRefreshAgent ? (
        <div className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-xs sm:flex-row sm:items-center sm:justify-between">
          <span className="text-muted">
            <span className="font-semibold text-foreground">No trading agent yet.</span> Deposit first, then refresh.
          </span>
          <Button size="sm" onClick={onRefreshAgent} disabled={refreshing}>
            <RefreshCw size={13} className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
            {refreshing ? "Refreshing…" : "Refresh agent"}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
