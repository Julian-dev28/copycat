"use client";

import { Download, Eye, KeyRound } from "lucide-react";
import { useId } from "react";
import { Button } from "@/components/ui/Button";
import { backupFilename, backupText, downloadText } from "@/lib/account/secrets";
import type { CreateEvent, CreateState } from "@/lib/account/createFlow";
import { AddressChip } from "@/components/ui/AddressChip";
import { CopyButton } from "./bits";

type Reveal = Extract<CreateState, { step: "reveal" }>;

/** The private key, once. Blurred until clicked; the dialog cannot close until "I saved my key". */
export function KeyReveal({ state, dispatch }: { state: Reveal; dispatch: (e: CreateEvent) => void }) {
  const id = useId();
  const { account, privateKey, warning, revealed, saved } = state;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-semibold">{account.label}</span>
        <AddressChip address={account.address} />
      </div>
      <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-xs text-muted">
        <p className="font-semibold text-foreground">Back up this key now. copycat will never show it again.</p>
        <p className="mt-0.5">{warning}</p>
      </div>
      <div className="relative">
        <div
          className={`rounded-lg border border-border bg-surface-2 p-3 font-num text-xs break-all select-all ${revealed ? "" : "blur-sm select-none"}`}
          aria-hidden={!revealed}
          translate="no"
        >
          {revealed ? privateKey : "0x" + "•".repeat(64)}
        </div>
        {!revealed ? (
          <button
            type="button"
            onClick={() => dispatch({ type: "reveal" })}
            className="absolute inset-0 flex items-center justify-center gap-2 rounded-lg text-sm font-medium text-foreground hover:bg-surface-2/40"
          >
            <Eye size={15} aria-hidden="true" /> Click to reveal the private key
          </button>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <CopyButton text={privateKey} label="Copy key" secret />
        <button
          type="button"
          onClick={() => downloadText(backupFilename(account.label, account.address), backupText({ label: account.label, address: account.address, privateKey, warning, nowMs: Date.now() }))}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs font-medium hover:bg-border"
        >
          <Download size={13} aria-hidden="true" /> Download backup .txt
        </button>
      </div>
      <label htmlFor={`${id}-saved`} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border px-3 py-2.5 text-sm">
        <input
          id={`${id}-saved`}
          type="checkbox"
          checked={saved}
          onChange={(e) => dispatch({ type: "toggleSaved", saved: e.target.checked })}
          className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
        />
        <span>
          <span className="font-medium">I saved my key somewhere safe.</span>
          <span className="block text-xs text-muted">Offline, not in chat or cloud notes. With it, you can reach the funds from any wallet, even without copycat.</span>
        </span>
      </label>
      <Button variant="primary" onClick={() => dispatch({ type: "continue" })} disabled={!saved}>
        <KeyRound size={15} aria-hidden="true" /> Continue to funding
      </Button>
    </div>
  );
}
