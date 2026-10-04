"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { formatUsd } from "@/lib/format";

/** First copy of a wallet while trading is live: real orders go out, say so once. */
export function LiveCopyDialog({ open, name, amount, onCancel, onConfirm }: { open: boolean; name: string; amount: number; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title="Copy with real money?"
      description={
        <>
          Trading is live (enabled, dry run off). copycat will place real orders on Hyperliquid now, mirroring {name} with up to{" "}
          <b className="text-foreground">{formatUsd(amount)}</b> of margin, and keep following every trade until you stop.
        </>
      }
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={onConfirm}>Copy for real</Button>
        </>
      }
    />
  );
}

/** Stop: close now vs let the open copies follow him out. */
export function StopDialog({
  open,
  name,
  openCopies,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  name: string;
  openCopies: number;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (closePositions: boolean) => void;
}) {
  const [close, setClose] = useState(true);
  const options = [
    { value: true, title: "Close positions now", text: `Market-close your ${openCopies} open cop${openCopies === 1 ? "y" : "ies"} of ${name} (reduce-only) and free the margin.` },
    { value: false, title: "Let open copies run out", text: "Open nothing new. Each open copy closes when he closes his position, so you keep his exits." },
  ];
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={`Stop copying ${name}?`}
      description="Either way the wallet stops opening new copies right away."
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>Keep copying</Button>
          <Button variant="danger" onClick={() => onConfirm(close)} disabled={pending}>
            {pending ? "Stopping…" : close ? "Stop and close" : "Stop new copies"}
          </Button>
        </>
      }
    >
      <div role="radiogroup" aria-label="What happens to open copies" className="flex flex-col gap-2">
        {options.map((o) => (
          <label key={String(o.value)} className={clsx("flex cursor-pointer gap-2 rounded-lg border p-3", close === o.value ? "border-accent bg-accent-soft/50" : "border-border")}>
            <input type="radio" name="stop-mode" className="mt-1 accent-[var(--accent)]" checked={close === o.value} onChange={() => setClose(o.value)} />
            <span>
              <span className="block text-sm font-medium">{o.title}</span>
              <span className="block text-xs text-muted">{o.text}</span>
            </span>
          </label>
        ))}
      </div>
    </Dialog>
  );
}
