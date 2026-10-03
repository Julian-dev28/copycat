"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";
import { clsx } from "clsx";
import { explorerUrl } from "@/lib/address";
import { shortenAddress } from "@/lib/format";

/**
 * Short address + copy-to-clipboard + Hyperliquid explorer link. Buttons
 * stop propagation so the chip can sit inside a clickable row.
 */
export function AddressChip({ address, className, strong }: { address: string; className?: string; strong?: boolean }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy(e: MouseEvent) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(address);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (insecure origin / permissions): the full address is in the title tooltip
    }
  }

  return (
    <span className={clsx("inline-flex items-center gap-0.5", className)}>
      <span
        className={clsx("font-num text-sm", strong ? "font-medium text-foreground" : "text-muted")}
        title={address}
      >
        {shortenAddress(address)}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Address copied" : `Copy address ${address}`}
        title={copied ? "Copied" : "Copy address"}
        className="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        {copied ? <Check size={13} className="text-success" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
      </button>
      <a
        href={explorerUrl(address)}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        aria-label={`Open ${address} in the Hyperliquid explorer`}
        title="Open in Hyperliquid explorer"
        className="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent"
      >
        <ExternalLink size={13} aria-hidden="true" />
      </a>
      <span role="status" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </span>
  );
}
