"use client";

import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { isValidAddress, normAddr } from "@/lib/address";
import { accountErrorText } from "@/lib/account/errors";
import type { AccountSummary } from "@/lib/account/types";
import { formatUsd, shortenAddress } from "@/lib/format";
import { ErrorLine, Field, SecretInput } from "./bits";
import { useAccountMode, useAccounts, useAction } from "./hooks";

/** usdSend from a copycat-created account. Its main key signs, unlocked by the passphrase. */
export function TransferDialog({ summary, open, onClose }: { summary: AccountSummary; open: boolean; onClose: () => void }) {
  const id = useId();
  const { source } = useAccountMode();
  const others = (useAccounts().data ?? []).filter((a) => a.id !== summary.account.id);
  const act = useAction();
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [pass, setPass] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const max = summary.balances.withdrawable_usd;
  const amt = Number(amount);

  const err = !isValidAddress(to) ? "Enter a 0x address to send to."
    : normAddr(to) === normAddr(summary.account.address) ? "That is this account."
    : !(amt > 0) ? "Enter an amount."
    : amt > max ? `At most ${formatUsd(max)} is withdrawable right now.`
    : !pass ? "Enter the passphrase." : null;

  function close() {
    setPass("");
    setSent(null);
    act.clearError();
    onClose();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (err) return;
    const ok = await act.run(async () => {
      await source.transfer({ from_account_id: summary.account.id, to_address: normAddr(to), amount_usd: amt, passphrase: pass });
      return true;
    });
    setPass("");
    if (ok) setSent(`Sent ${formatUsd(amt)} to ${shortenAddress(to)}.`);
  }

  return (
    <Dialog open={open} onClose={close} title={`Send USDC from ${summary.account.label}`} description="A Hyperliquid USDC send: instant, no gas. Only this account's own key can do it.">
      {sent ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-success" role="status">{sent}</p>
          <Button onClick={close}>Done</Button>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-3" autoComplete="off" noValidate>
          <Field label="To" htmlFor={`${id}-to`} hint={others.length ? (
            <span className="flex flex-wrap gap-1">
              {others.map((a) => (
                <button key={a.id} type="button" onClick={() => setTo(a.address)} className="rounded-md border border-border px-1.5 py-0.5 hover:border-accent/60">{a.label}</button>
              ))}
            </span>
          ) : undefined}>
            <Input id={`${id}-to`} value={to} onChange={(e) => setTo(e.target.value)} placeholder="0x…" className="font-num" spellCheck={false} autoComplete="off" />
          </Field>
          <Field label="Amount" htmlFor={`${id}-amt`} hint={<button type="button" onClick={() => setAmount(String(Math.floor(max * 100) / 100))} className="hover:text-foreground">Max {formatUsd(max)}</button>}>
            <Input id={`${id}-amt`} type="number" inputMode="decimal" min={0} step="0.01" leading="$" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Passphrase" htmlFor={`${id}-pass`}>
            <SecretInput id={`${id}-pass`} value={pass} onChange={(e) => setPass(e.target.value)} />
          </Field>
          <ErrorLine>{to || amount ? err : null}</ErrorLine>
          <ErrorLine>{accountErrorText(act.error, "transfer")}</ErrorLine>
          <div className="flex justify-end gap-2">
            <Button onClick={close}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={Boolean(err) || act.pending}>{act.pending ? "Sending…" : "Send"}</Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
