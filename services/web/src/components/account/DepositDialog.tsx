"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useId, useReducer, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Notice } from "@/components/ui/Notice";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { canRetrySend, connectDeposit, depositReducer, initialDeposit, sendDeposit } from "@/lib/account/depositFlow";
import { depositProblem, floorCents, isCredited } from "@/lib/account/funding";
import type { AccountSummary, FundingInfo } from "@/lib/account/types";
import { formatUsd, shortenAddress } from "@/lib/format";
import { CopyButton, ErrorLine, Field } from "./bits";
import { QrCode } from "./FundPanel";
import { accountKeys, useAccountMode } from "./hooks";

type Method = "arbitrum" | "hyperliquid" | "exchange";
const METHODS = [
  { value: "arbitrum" as const, label: "From Arbitrum" },
  { value: "hyperliquid" as const, label: "From Hyperliquid" },
  { value: "exchange" as const, label: "From an exchange" },
];

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="text-muted">{label}</span>
      <span className="min-w-0 truncate text-right font-num text-foreground">{children}</span>
    </div>
  );
}

function AddressBlock({ address, steps }: { address: string; steps: string[] }) {
  return (
    <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
      <div className="flex flex-col items-center gap-2">
        <QrCode text={address} size={140} />
        <CopyButton text={address} label="Copy address" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium text-muted">This account&apos;s address</p>
        <p className="font-num text-xs break-all">{address}</p>
        <ol className="mt-2 flex list-decimal flex-col gap-1.5 pl-4 text-xs text-muted">
          {steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
      </div>
    </div>
  );
}

function FromArbitrum({ summary, info }: { summary: AccountSummary; info: FundingInfo }) {
  const id = useId();
  const { demo, source } = useAccountMode();
  const qc = useQueryClient();
  const [s, dispatch] = useReducer(depositReducer, initialDeposit);
  const [amount, setAmount] = useState("");
  const baseline = useRef<number | null>(null);
  // one wallet handle for the whole flow (the demo wallet keeps its chain and balance in it)
  const [provider] = useState(() => source.walletProvider());
  const deps = { provider, info };
  const held = summary.balances.perps_usd + summary.balances.spot_usd;
  const problem = s.step === "ready" || canRetrySend(s) ? depositProblem(amount, s.balanceUsd, info.min_deposit_usd) : null;
  const tooSmall = Boolean(problem && amount && problem.startsWith("The minimum"));

  // After the transfer is mined, poll balances until Hyperliquid credits it.
  useEffect(() => {
    if (s.step !== "confirmed") return;
    const t = setInterval(() => void qc.invalidateQueries({ queryKey: accountKeys.all(demo) }), 5000);
    return () => clearInterval(t);
  }, [s.step, qc, demo]);
  useEffect(() => {
    if (s.step === "confirmed" && baseline.current !== null && s.amountUsd && isCredited(baseline.current, held, s.amountUsd)) dispatch({ type: "credited" });
  }, [s.step, s.amountUsd, held]);

  async function send() {
    baseline.current = held;
    await sendDeposit(deps, amount, s.balanceUsd, dispatch);
  }

  const txLink = s.txHash ? `${info.explorer_url}/tx/${s.txHash}` : null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface-2 px-3 py-2">
        <Fact label="Network">{info.chain_name}</Fact>
        <Fact label="Token">native USDC {shortenAddress(info.usdc_address)}</Fact>
        <Fact label="To">Hyperliquid bridge {shortenAddress(info.bridge_address)}</Fact>
        <Fact label="From">this account {shortenAddress(info.account_address)}</Fact>
        <Fact label="Minimum">{info.min_deposit_usd} USDC</Fact>
      </div>
      <p className="text-xs text-muted">
        The bridge credits the address that <span className="font-semibold text-foreground">sends</span> the USDC, so your wallet must be on this account&apos;s own address. Below {info.min_deposit_usd} USDC a deposit is never credited and is lost.
      </p>
      {info.account_kind === "created" && s.step === "idle" ? (
        <Notice tone="info" title="copycat holds this wallet's key">
          No browser wallet can send from it unless you import its backup key into one. Otherwise use From Hyperliquid or From an exchange.
        </Notice>
      ) : null}

      {s.step === "idle" || (s.step === "error" && !canRetrySend(s) && !s.txHash) ? (
        <Button variant="primary" onClick={() => void connectDeposit(deps, dispatch)}>Connect wallet</Button>
      ) : null}
      {["connecting", "switching", "reading"].includes(s.step) ? (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          {s.step === "connecting" ? "Connecting your wallet…" : s.step === "switching" ? `Switching to ${info.chain_name}…` : "Reading your USDC balance…"}
        </p>
      ) : null}

      {s.step === "ready" || canRetrySend(s) ? (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (!problem) void send(); }} noValidate>
          <Field label="Amount" htmlFor={`${id}-amt`} hint={<button type="button" className="hover:text-foreground" onClick={() => setAmount(String(floorCents(s.balanceUsd ?? 0)))}>Wallet {formatUsd(s.balanceUsd)}</button>}>
            <Input id={`${id}-amt`} inputMode="decimal" leading="$" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={`${info.min_deposit_usd} or more`} aria-invalid={Boolean(problem && amount)} />
          </Field>
          {tooSmall ? <Notice tone="danger" title="Below the minimum deposit">{problem}</Notice> : <ErrorLine>{amount ? problem : null}</ErrorLine>}
          <Button type="submit" variant="primary" disabled={Boolean(problem)}>Send {amount && !problem ? `${amount} USDC` : "USDC"} to the bridge</Button>
        </form>
      ) : null}

      {s.step === "confirming" ? <p className="text-sm text-muted" role="status">Confirm the transfer in your wallet…</p> : null}
      {txLink ? (
        <div className="flex flex-col gap-1 rounded-lg border border-border px-3 py-2 text-xs" role="status">
          <span className="flex items-center gap-2">
            {s.step === "pending" || s.step === "confirmed" ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : null}
            {s.step === "pending" ? "Waiting for Arbitrum to mine the transfer…"
              : s.step === "confirmed" ? `Mined. Hyperliquid credits ${formatUsd(s.amountUsd)} within ~1 minute; watching your balance…`
              : s.step === "credited" ? <span className="text-success">Credited: {formatUsd(s.amountUsd)} arrived on Hyperliquid.</span>
              : "Transfer sent."}
          </span>
          <a href={txLink} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-num text-accent hover:underline">
            {shortenAddress(s.txHash ?? "", 10, 8)} <ExternalLink size={11} aria-hidden="true" />
          </a>
        </div>
      ) : null}
      {s.error ? <ErrorLine>{s.error.message}</ErrorLine> : null}
    </div>
  );
}

export function DepositDialog({ summary, info, open, onClose }: { summary: AccountSummary; info: FundingInfo | undefined; open: boolean; onClose: () => void }) {
  const [method, setMethod] = useState<Method>("arbitrum");
  const address = summary.account.address;
  return (
    <Dialog open={open} onClose={onClose} title={`Deposit to ${summary.account.label}`} description="USDC on Hyperliquid is what copycat trades with.">
      <div className="flex flex-col gap-4">
        <SegmentedControl options={METHODS} value={method} onChange={setMethod} aria-label="Deposit method" />
        {method === "arbitrum" ? (
          info ? (open ? <FromArbitrum key={summary.account.id} summary={summary} info={info} /> : null) : <p className="text-sm text-muted">Loading the bridge details…</p>
        ) : null}
        {method === "hyperliquid" ? (
          <AddressBlock address={address} steps={[
            "In the other Hyperliquid account (app.hyperliquid.xyz, Portfolio, Send), send USDC to this address.",
            "It lands in seconds, no gas. From another copycat account, use Send on that account.",
          ]} />
        ) : null}
        {method === "exchange" ? (
          <AddressBlock address={address} steps={[
            "Withdraw USDC from the exchange and pick the Hyperliquid network, with this address as the destination.",
            "Do not pick Arbitrum: USDC sent on Arbitrum to this address stays on Arbitrum. If that already happened and you own this address in a browser wallet, use From Arbitrum.",
          ]} />
        ) : null}
        <div className="flex justify-end">
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
    </Dialog>
  );
}
