"use client";

import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { accountErrorText } from "@/lib/account/errors";
import { checkLabel, LABEL_MAX } from "@/lib/account/passphrase";
import type { TradingAccount } from "@/lib/account/types";
import { ErrorLine } from "./bits";
import { useAccountMode, useAction } from "./hooks";

export function RenameForm({ account, onDone }: { account: TradingAccount; onDone: () => void }) {
  const id = useId();
  const { source } = useAccountMode();
  const act = useAction();
  const [label, setLabel] = useState(account.label);
  const err = checkLabel(label);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (err) return;
    const ok = await act.run(async () => {
      await source.rename(account.id, label.trim());
      return true;
    });
    if (ok) onDone();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={id} className="sr-only">New name</label>
      <div className="flex gap-2">
        <Input id={id} value={label} maxLength={LABEL_MAX} onChange={(e) => setLabel(e.target.value)} autoFocus autoComplete="off" />
        <Button type="submit" size="sm" variant="primary" disabled={act.pending || Boolean(err)}>Save</Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
      <ErrorLine>{accountErrorText(act.error, "rename")}</ErrorLine>
    </form>
  );
}

/** Removal needs the account's name typed back: one slip should not drop a wallet. */
export function RemoveConfirm({ account, onDone }: { account: TradingAccount; onDone: () => void }) {
  const id = useId();
  const { source } = useAccountMode();
  const act = useAction();
  const [typed, setTyped] = useState("");
  const match = typed.trim() === account.label.trim();

  async function remove() {
    const ok = await act.run(async () => {
      await source.remove(account.id);
      return true;
    });
    if (ok) onDone();
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-danger/40 bg-danger/5 p-3 text-xs">
      <p className="font-semibold text-foreground">Remove {account.label} from copycat?</p>
      <ul className="list-disc pl-4 text-muted">
        {account.active ? <li>It is the active account: copycat stops trading until you activate another.</li> : null}
        {account.kind === "created" ? <li>copycat deletes its encrypted key. Your backup file is then the only way to reach the funds.</li> : null}
        <li>Funds stay on Hyperliquid. Removing only forgets the keys on this machine.</li>
      </ul>
      <label htmlFor={id} className="text-muted">
        Type <span className="font-semibold text-foreground">{account.label}</span> to confirm
      </label>
      <div className="flex gap-2">
        <Input id={id} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />
        <Button size="sm" variant="danger" disabled={!match || act.pending} onClick={remove}>
          {act.pending ? "Removing…" : "Remove"}
        </Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
      <ErrorLine>{accountErrorText(act.error, "remove")}</ErrorLine>
    </div>
  );
}
