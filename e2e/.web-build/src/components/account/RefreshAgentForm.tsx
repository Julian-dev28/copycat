"use client";

import { CheckCircle2, RefreshCw } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { agentView } from "@/lib/account/agent";
import { accountErrorText } from "@/lib/account/errors";
import type { TradingAccount } from "@/lib/account/types";
import { useNow } from "@/hooks/useNow";
import { AgentBanner, ErrorLine, Field, SecretInput } from "./bits";
import { useAccountMode, useAction } from "./hooks";

/** Created wallets: the passphrase unlocks the main key on the server just long enough to sign a new approveAgent. */
export function RefreshAgentForm({ account, onDone }: { account: TradingAccount; onDone: () => void }) {
  const id = useId();
  const now = useNow();
  const { source } = useAccountMode();
  const act = useAction();
  const [pass, setPass] = useState("");
  const [done, setDone] = useState(false);
  const v = agentView(account, now);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await source.refreshAgent(account.id, pass);
      return true;
    });
    setPass("");
    if (ok) setDone(true);
  }

  if (done) {
    return (
      <div className="flex flex-col items-center gap-3 py-2 text-center">
        <CheckCircle2 size={36} className="text-success" aria-hidden="true" />
        <p className="text-base font-semibold">Trading agent renewed for {account.label}</p>
        <Button onClick={onDone}>Done</Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" autoComplete="off">
      <p className="text-sm text-muted">
        Agent: <span className="font-medium text-foreground">{v.label}</span>. {v.status === "missing" ? "Make sure the wallet is funded first: Hyperliquid refuses agents for empty accounts." : "A new agent replaces the old one."}
      </p>
      <AgentBanner compact />
      <Field label={`Passphrase for ${account.label}`} htmlFor={id}>
        <SecretInput id={id} value={pass} onChange={(e) => setPass(e.target.value)} autoFocus />
      </Field>
      <ErrorLine>{accountErrorText(act.error, "refresh-agent")}</ErrorLine>
      <Button type="submit" variant="primary" disabled={act.pending || !pass}>
        <RefreshCw size={14} className={act.pending ? "animate-spin" : undefined} aria-hidden="true" />
        {act.pending ? "Signing a new agent…" : "Refresh agent"}
      </Button>
    </form>
  );
}
