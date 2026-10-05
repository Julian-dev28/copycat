"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2 } from "lucide-react";
import { useId, useReducer, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Notice } from "@/components/ui/Notice";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { normAddr } from "@/lib/address";
import { actionReducer, initialAction, isBusy, runAction } from "@/lib/account/actionFlow";
import {
  actionCap, actionProblem, emptyForm, floorCents, isOtherDestination, parseUsd, signerPath, withdrawDestination, type ActionForm,
} from "@/lib/account/funding";
import type { AccountSummary, FundingInfo, UserActionKind, UserActionPrepareRequest } from "@/lib/account/types";
import { formatUsd, shortenAddress } from "@/lib/format";
import { ErrorLine, Field, SecretInput } from "./bits";
import { accountKeys, useAccountMode, useAccounts } from "./hooks";

const TITLE: Record<UserActionKind, string> = { usd_class_transfer: "Move USDC", usd_send: "Send USDC", withdraw: "Withdraw to Arbitrum" };
const DESC: Record<UserActionKind, string> = {
  usd_class_transfer: "Between this account's spot and perps balances. Instant, no gas.",
  usd_send: "A Hyperliquid USDC send to another of your copycat accounts. Instant, no gas.",
  withdraw: "Hyperliquid's validators send USDC to Arbitrum through the bridge.",
};
const HL_APP_STEPS: Record<UserActionKind, string> = {
  usd_class_transfer: "Portfolio, then Perps ⇄ Spot (Transfer), pick the direction and the amount.",
  usd_send: "Portfolio, then Send, paste the destination address, USDC, amount.",
  withdraw: "Portfolio, then Withdraw, amount (the 1 USDC fee is shown there too).",
};
const STEP_TEXT: Record<string, string> = {
  connecting: "Connecting your wallet…", preparing: "Preparing the request…", switching: "Switching your wallet's network…",
  signing: "Sign in your wallet…", submitting: "Sending to Hyperliquid…",
};

function HlAppHowTo({ kind, address }: { kind: UserActionKind; address: string }) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="text-muted">
        Only the wallet that owns {shortenAddress(address)} can sign this, and no browser wallet is available here. Do it on Hyperliquid&apos;s own app instead:
      </p>
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-xs text-muted">
        <li>Open app.hyperliquid.xyz and connect the wallet that owns {shortenAddress(address)}.</li>
        <li>{HL_APP_STEPS[kind]}</li>
        <li>Come back here: balances refresh within a minute.</li>
      </ol>
      <a href="https://app.hyperliquid.xyz/portfolio" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
        Open Hyperliquid <ExternalLink size={12} aria-hidden="true" />
      </a>
    </div>
  );
}

export function MoneyActionDialog({
  kind, summary, info, open, onClose, initialToPerp = true,
}: {
  kind: UserActionKind;
  summary: AccountSummary;
  info: FundingInfo | undefined;
  open: boolean;
  onClose: () => void;
  initialToPerp?: boolean;
}) {
  const id = useId();
  const qc = useQueryClient();
  const { demo, source } = useAccountMode();
  const account = summary.account;
  const others = (useAccounts().data ?? []).filter((a) => a.id !== account.id);
  const [provider] = useState(() => source.walletProvider());
  const path = signerPath(account, provider !== null);
  const [form, setForm] = useState<ActionForm>(() => emptyForm(initialToPerp));
  const [s, dispatch] = useReducer(actionReducer, initialAction);
  const set = (patch: Partial<ActionForm>) => setForm((f) => ({ ...f, ...patch }));
  const limits = info?.limits;
  const fee = info?.withdraw_fee_usd ?? 1;
  const cap = actionCap(kind, form.toPerp, limits);
  const problem = info ? actionProblem(kind, form, { limits, feeUsd: fee, own: account.address, others: others.map((a) => a.address), needsPassphrase: path === "passphrase" }) : "Loading…";
  const otherDest = kind === "withdraw" && isOtherDestination(form, account.address);
  const amt = parseUsd(form.amount);

  function close() {
    setForm(emptyForm(initialToPerp));
    dispatch({ type: "reset" });
    onClose();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (problem || isBusy(s) || amt === null) return;
    const req: UserActionPrepareRequest = { kind, amount_usd: amt };
    if (kind === "usd_class_transfer") req.to_perp = form.toPerp;
    if (kind === "usd_send") req.destination = normAddr(form.destination);
    if (kind === "withdraw" && otherDest) {
      req.destination = withdrawDestination(form, account.address);
      req.confirm_destination = normAddr(form.confirm);
    }
    const pass = path === "passphrase" ? form.passphrase : null;
    set({ passphrase: "" });
    const out = await runAction(
      { path, accountId: account.id, own: account.address, provider, prepare: source.prepareAction, submit: source.submitAction, run: source.runAction },
      req, pass, dispatch,
    );
    if (out) void qc.invalidateQueries({ queryKey: accountKeys.all(demo) });
  }

  return (
    <Dialog open={open} onClose={close} title={`${TITLE[kind]} · ${account.label}`} description={DESC[kind]}>
      {s.step === "done" && s.result ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-success" role="status">{s.result.message}</p>
          <Button onClick={close}>Done</Button>
        </div>
      ) : path === "hl_app" ? (
        <div className="flex flex-col gap-3">
          <HlAppHowTo kind={kind} address={account.address} />
          <div className="flex justify-end"><Button onClick={close}>Close</Button></div>
        </div>
      ) : kind === "usd_class_transfer" && limits?.unified ? (
        <div className="flex flex-col gap-3">
          <Notice tone="info" title="Unified account">
            Spot and perps share one USDC balance on this account, so there is nothing to move: copycat can already trade with all of it.
          </Notice>
          <div className="flex justify-end"><Button onClick={close}>Close</Button></div>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-3" autoComplete="off" noValidate>
          {kind === "usd_class_transfer" ? (
            <SegmentedControl
              aria-label="Direction"
              value={form.toPerp ? "to_perp" : "to_spot"}
              onChange={(v) => set({ toPerp: v === "to_perp", amount: "" })}
              options={[{ value: "to_perp", label: "Spot → Perps" }, { value: "to_spot", label: "Perps → Spot" }]}
            />
          ) : null}
          {kind === "usd_send" ? (
            <Field label="To" htmlFor={`${id}-to`}>
              {others.length ? (
                <div id={`${id}-to`} role="radiogroup" aria-label="Destination account" className="flex flex-wrap gap-1.5">
                  {others.map((a) => {
                    const on = normAddr(form.destination) === a.address;
                    return (
                      <button key={a.id} type="button" role="radio" aria-checked={on} onClick={() => set({ destination: a.address })}
                        className={`rounded-md border px-2 py-1 text-xs ${on ? "border-accent bg-accent-soft text-foreground" : "border-border text-muted hover:border-accent/60"}`}>
                        {a.label} <span className="font-num">{shortenAddress(a.address)}</span>
                      </button>
                    );
                  })}
                </div>
              ) : <p className="text-xs text-muted">No other account in this copycat yet. Sends only go to your own accounts.</p>}
            </Field>
          ) : null}
          {kind === "withdraw" ? (
            <>
              <Field label="To (Arbitrum)" htmlFor={`${id}-dest`} hint={otherDest ? <span className="text-warning">another address</span> : "this account"}>
                <Input id={`${id}-dest`} value={form.destination} onChange={(e) => set({ destination: e.target.value, confirm: "" })} placeholder={account.address} className="font-num" spellCheck={false} />
              </Field>
              {otherDest ? (
                <Field label="Type the destination again" htmlFor={`${id}-confirm`}>
                  <Input id={`${id}-confirm`} value={form.confirm} onChange={(e) => set({ confirm: e.target.value })} placeholder="0x…" className="font-num" spellCheck={false} onPaste={(e) => e.preventDefault()} />
                </Field>
              ) : null}
            </>
          ) : null}
          <Field label="Amount" htmlFor={`${id}-amt`} hint={<button type="button" onClick={() => set({ amount: String(floorCents(cap ?? 0)) })} className="hover:text-foreground">Max {formatUsd(cap)}</button>}>
            <Input id={`${id}-amt`} inputMode="decimal" leading="$" value={form.amount} onChange={(e) => set({ amount: e.target.value })} />
          </Field>
          {kind === "withdraw" ? (
            <p className="text-xs text-muted">
              Fee {formatUsd(fee)}, taken by Hyperliquid. You receive about {formatUsd(amt !== null && amt > fee ? amt - fee : 0)} on Arbitrum in ~5 minutes.
            </p>
          ) : null}
          {path === "passphrase" ? (
            <Field label="Passphrase" htmlFor={`${id}-pass`}>
              <SecretInput id={`${id}-pass`} value={form.passphrase} onChange={(e) => set({ passphrase: e.target.value })} />
            </Field>
          ) : (
            <p className="text-xs text-muted">Your browser wallet on {shortenAddress(account.address)} signs this. copycat cannot move funds without that signature.</p>
          )}
          {isBusy(s) ? (
            <p className="flex items-center gap-2 text-sm text-muted" role="status"><Loader2 size={14} className="animate-spin" aria-hidden="true" />{STEP_TEXT[s.step]}</p>
          ) : null}
          <ErrorLine>{form.amount || form.destination ? problem : null}</ErrorLine>
          <ErrorLine>{s.error?.message}</ErrorLine>
          <div className="flex justify-end gap-2">
            <Button onClick={close}>Cancel</Button>
            <Button type="submit" variant={kind === "withdraw" ? "danger" : "primary"} disabled={Boolean(problem) || isBusy(s)}>
              {TITLE[kind].split(" ")[0]}{amt ? ` ${formatUsd(amt)}` : ""}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
