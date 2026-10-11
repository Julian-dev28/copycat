"use client";

import { clsx } from "clsx";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { checkLabel, checkPassphrase, LABEL_MAX, passphraseStrength, STRENGTH_META } from "@/lib/account/passphrase";
import { ErrorLine, Field, SecretInput } from "./bits";

const BAR = ["bg-danger", "bg-warning", "bg-success"];

function StrengthMeter({ value }: { value: string }) {
  const s = passphraseStrength(value);
  const meta = STRENGTH_META[s];
  return (
    <div className="flex flex-col gap-1" aria-live="polite">
      <div className="flex gap-1" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <span key={i} className={clsx("h-1 flex-1 rounded-full", i <= meta.bars ? BAR[meta.bars - 1] : "bg-surface-2")} />
        ))}
      </div>
      <span className="text-[11px] text-muted">
        {value ? <span className="font-medium text-foreground">{meta.label}. </span> : null}
        {meta.hint}
      </span>
    </div>
  );
}

/**
 * Label + passphrase twice. The passphrase lives in this component's state
 * until submit, then the parent sends it once; it is never lifted further.
 */
export function CreateForm({ onSubmit, pending, error }: { onSubmit: (label: string, passphrase: string) => void; pending: boolean; error: string }) {
  const id = useId();
  const [label, setLabel] = useState("");
  const [pass, setPass] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);
  const labelErr = checkLabel(label);
  const passCheck = checkPassphrase(pass, confirm);

  function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (labelErr || !passCheck.ok) return;
    onSubmit(label.trim(), pass);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" autoComplete="off" noValidate>
      <p className="text-sm text-muted">
        copycat generates a fresh Hyperliquid wallet on this machine and encrypts its key with your passphrase. You get the key once, to back it up.
      </p>
      <Field label="Name" htmlFor={`${id}-label`} hint="Only you see this.">
        <Input id={`${id}-label`} value={label} maxLength={LABEL_MAX} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Copy account" autoComplete="off" />
      </Field>
      <Field label="Passphrase" htmlFor={`${id}-pass`} hint={<StrengthMeter value={pass} />}>
        <SecretInput id={`${id}-pass`} value={pass} onChange={(e) => setPass(e.target.value)} placeholder="At least 12 characters" />
      </Field>
      <Field label="Passphrase again" htmlFor={`${id}-confirm`} hint="Needed to send funds and renew the trading agent. Nobody can reset it.">
        <SecretInput id={`${id}-confirm`} value={confirm} onChange={(e) => setConfirm(e.target.value)} peek={false} />
      </Field>
      <ErrorLine>{touched ? labelErr ?? passCheck.error : null}</ErrorLine>
      <ErrorLine>{error}</ErrorLine>
      <Button type="submit" variant="primary" disabled={pending}>
        {pending ? "Creating wallet…" : "Create wallet"}
      </Button>
    </form>
  );
}
