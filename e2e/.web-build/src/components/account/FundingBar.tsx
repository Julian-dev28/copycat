"use client";

import { ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, Send } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { moveHint } from "@/lib/account/funding";
import type { AccountSummary, UserActionKind } from "@/lib/account/types";
import { formatUsd } from "@/lib/format";
import { DepositDialog } from "./DepositDialog";
import { useAccountSummary, useFundingInfo } from "./hooks";
import { MoneyActionDialog } from "./MoneyActionDialog";

type Open = "deposit" | UserActionKind | null;

/**
 * Deposit / Move / Withdraw / Send for the account on screen. "Move to perps"
 * is pushed up front when perps is about empty while spot holds USDC (the
 * engine sizes from perps on a standard account). Unified accounts get no
 * Move: one balance, nothing to move.
 */
export function FundingBar({ summary, compact }: { summary: AccountSummary; compact?: boolean }) {
  const [open, setOpen] = useState<Open>(null);
  const [toPerp, setToPerp] = useState(true);
  const funding = useFundingInfo(summary.account.id, open === "deposit");
  const info = funding.data;
  const limits = info?.limits;
  const hint = moveHint(summary.balances, limits);
  const unified = Boolean(limits?.unified);
  const close = () => setOpen(null);
  const move = (perp: boolean) => {
    setToPerp(perp);
    setOpen("usd_class_transfer");
  };

  return (
    <div className="flex flex-col gap-3">
      {hint && limits ? (
        <Notice
          tone="warning"
          title={`Your USDC is in spot: ${formatUsd(limits.spot_usdc_free_usd)} spot, ${formatUsd(summary.balances.perps_usd)} perps`}
          action={<Button size="sm" variant="primary" onClick={() => move(true)}><ArrowLeftRight size={13} aria-hidden="true" /> Move to perps</Button>}
        >
          On a standard Hyperliquid account, perps trading only uses the perps balance. Move spot USDC to perps so copycat can size copies with it.
        </Notice>
      ) : null}
      <div className={`flex flex-wrap gap-2 ${compact ? "" : "sm:justify-start"}`} role="group" aria-label="Funding">
        <Button variant="primary" onClick={() => setOpen("deposit")}><ArrowDownToLine size={14} aria-hidden="true" /> Deposit</Button>
        {!unified ? <Button onClick={() => move(true)}><ArrowLeftRight size={14} aria-hidden="true" /> Move</Button> : null}
        <Button onClick={() => setOpen("withdraw")}><ArrowUpFromLine size={14} aria-hidden="true" /> Withdraw</Button>
        <Button onClick={() => setOpen("usd_send")}><Send size={14} aria-hidden="true" /> Send</Button>
      </div>
      {unified ? <p className="text-[11px] text-muted">Unified account: spot and perps share one USDC balance, no moves needed.</p> : null}
      {funding.isError ? <p className="text-[11px] text-warning">Funding details could not be loaded; retrying.</p> : null}
      <DepositDialog summary={summary} info={info} open={open === "deposit"} onClose={close} />
      {open && open !== "deposit" ? (
        <MoneyActionDialog key={`${open}-${toPerp}`} kind={open} summary={summary} info={info} open onClose={close} initialToPerp={toPerp} />
      ) : null}
    </div>
  );
}

/** The wallet manager's fund step: the same bar for an account that is not on screen yet. */
export function FundingBarFor({ accountId }: { accountId: string }) {
  const summary = useAccountSummary(accountId);
  if (!summary.data) return <p className="text-xs text-muted">{summary.isError ? "Balances could not be loaded; retrying." : "Loading balances…"}</p>;
  return <FundingBar summary={summary.data} compact />;
}
