"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { useId, useReducer, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { setDemoWalletMode } from "@/lib/account/demo";
import { DEMO_WALLET_MODES, type DemoWalletMode } from "@/lib/account/fixtures";
import { checkLabel, LABEL_MAX } from "@/lib/account/passphrase";
import { initialSign, runSignFlow, signReducer } from "@/lib/account/signFlow";
import { isBusy, signSteps } from "@/lib/account/signView";
import type { TradingAccount } from "@/lib/account/types";
import { shortenAddress } from "@/lib/format";
import { ErrorLine, Field } from "./bits";
import { accountKeys, useAccountMode } from "./hooks";
import { StepProgress } from "./StepProgress";

/**
 * Connect a browser wallet and approve a copycat agent. The agent key is
 * made and spent inside runSignFlow; this component only sees SignState.
 * `refresh` = renewing an existing account: label fixed, wallet must match.
 */
export function SignWithWallet({ refresh, onDone }: { refresh?: { label: string; address: string }; onDone: (a: TradingAccount) => void }) {
  const id = useId();
  const { demo, source } = useAccountMode();
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(signReducer, initialSign);
  const [label, setLabel] = useState(refresh?.label ?? "");
  const [touched, setTouched] = useState(false);
  const [demoMode, setDemoMode] = useState<DemoWalletMode>("approve");
  const labelErr = checkLabel(label);
  const busy = isBusy(state);

  async function start() {
    setTouched(true);
    if (labelErr) return;
    if (demo) setDemoWalletMode(demoMode);
    const account = await runSignFlow(
      { provider: source.walletProvider(), label: label.trim(), expectedAddress: refresh?.address, prepare: source.prepare, submit: source.submit },
      dispatch,
    );
    if (account) {
      void qc.invalidateQueries({ queryKey: accountKeys.all(demo) });
      onDone(account);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {refresh ? (
        <p className="text-sm text-muted">
          Sign a new agent approval with <span className="font-num text-foreground">{shortenAddress(refresh.address)}</span>. The old agent stops when this one is approved.
        </p>
      ) : (
        <Field label="Name" htmlFor={`${id}-label`} hint="Only you see this.">
          <Input id={`${id}-label`} value={label} maxLength={LABEL_MAX} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Rabby main" disabled={busy} autoComplete="off" />
        </Field>
      )}
      <StepProgress steps={signSteps(state)} />
      <ErrorLine>{touched && !refresh ? labelErr : null}</ErrorLine>
      {demo ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted">
          <label htmlFor={`${id}-demo`}>Demo wallet</label>
          <select
            id={`${id}-demo`}
            value={demoMode}
            disabled={busy}
            onChange={(e) => {
              setDemoMode(e.target.value as DemoWalletMode);
            }}
            className="rounded-md border border-border bg-surface-2 px-2 py-1 text-xs text-foreground"
          >
            {DEMO_WALLET_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <span>signs for real with a throwaway key; starts on Ethereum so you see the network switch.</span>
        </div>
      ) : null}
      {state.step === "done" ? null : (
        <Button variant="primary" onClick={start} disabled={busy}>
          <Wallet size={15} aria-hidden="true" />
          {busy ? "Waiting for your wallet…" : state.step === "error" ? "Try again" : "Connect wallet"}
        </Button>
      )}
    </div>
  );
}
