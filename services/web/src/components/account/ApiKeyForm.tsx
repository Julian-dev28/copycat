"use client";

import { ExternalLink, FileKey } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { isValidAddress } from "@/lib/address";
import { accountErrorText } from "@/lib/account/errors";
import { checkLabel, LABEL_MAX } from "@/lib/account/passphrase";
import type { TradingAccount } from "@/lib/account/types";
import { ErrorLine, Field, SecretInput } from "./bits";
import { useAccountMode, useAccounts, useAction } from "./hooks";

const KEY_RE = /^(0x)?[0-9a-fA-F]{64}$/;

/** Main address + an API wallet key made on Hyperliquid. The key sits in this form's state only until submit. */
export function ApiKeyForm({ refresh, onDone }: { refresh?: { label: string; address: string }; onDone: (a: TradingAccount) => void }) {
  const id = useId();
  const { source } = useAccountMode();
  const accounts = useAccounts();
  const action = useAction();
  const env = useAction();
  const [label, setLabel] = useState(refresh?.label ?? "");
  const [address, setAddress] = useState(refresh?.address ?? "");
  const [key, setKey] = useState("");
  const [touched, setTouched] = useState(false);

  const err = checkLabel(label) ?? (!isValidAddress(address) ? "The main address must be 0x followed by 40 hex characters." : null)
    ?? (!KEY_RE.test(key.trim()) ? "The API wallet key is 0x followed by 64 hex characters." : null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (err) return;
    const k = key.trim();
    const acc = await action.run(() => source.importKey({ label: label.trim(), main_address: address.trim(), agent_private_key: k.startsWith("0x") ? k : `0x${k}` }));
    if (acc) {
      setKey("");
      onDone(acc);
    }
  }

  async function importEnv() {
    const list = await env.run(() => source.importEnv());
    if (list?.[0]) onDone(list[0]);
  }

  const showEnv = !refresh && accounts.isSuccess && accounts.data.length === 0;

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" autoComplete="off" noValidate>
      <p className="text-sm text-muted">
        Already made an API wallet on Hyperliquid? Paste it here. Create one under{" "}
        <a href="https://app.hyperliquid.xyz/API" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-medium text-accent hover:underline">
          app.hyperliquid.xyz/API <ExternalLink size={11} aria-hidden="true" />
        </a>
        : name it, click Generate, Authorize, and copy the private key it shows.
      </p>
      {showEnv ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-xs sm:flex-row sm:items-center sm:justify-between">
          <span className="text-muted">
            Your <span className="font-num text-foreground">.env</span> already has COPYCAT_ACCOUNT_ADDRESS and COPYCAT_AGENT_KEY? Use them in one click.
          </span>
          <Button size="sm" onClick={importEnv} disabled={env.pending}>
            <FileKey size={13} aria-hidden="true" /> {env.pending ? "Importing…" : "Import from .env"}
          </Button>
        </div>
      ) : null}
      <ErrorLine>{accountErrorText(env.error, "import-from-.env")}</ErrorLine>
      {refresh ? null : (
        <Field label="Name" htmlFor={`${id}-label`}>
          <Input id={`${id}-label`} value={label} maxLength={LABEL_MAX} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Main" autoComplete="off" />
        </Field>
      )}
      <Field label="Main account address" htmlFor={`${id}-addr`} hint="The wallet that holds the funds, not the API wallet's own address.">
        <Input id={`${id}-addr`} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="0x…" className="font-num" autoComplete="off" spellCheck={false} disabled={Boolean(refresh)} />
      </Field>
      <Field label="API wallet private key" htmlFor={`${id}-key`} hint="Stored encrypted on this machine. It can trade, it cannot withdraw.">
        <SecretInput id={`${id}-key`} value={key} onChange={(e) => setKey(e.target.value)} placeholder="0x… (64 hex characters)" />
      </Field>
      <ErrorLine>{touched ? err : null}</ErrorLine>
      <ErrorLine>{accountErrorText(action.error, "connect-by-API-key")}</ErrorLine>
      <Button type="submit" variant="primary" disabled={action.pending}>
        {action.pending ? "Checking the key…" : refresh ? "Replace key" : "Connect"}
      </Button>
    </form>
  );
}
