"use client";

import { useId, useState, type ClipboardEvent } from "react";
import { clsx } from "clsx";
import { Loader2, Plus, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { parseWalletInput, shortAddr } from "@/lib/scout/addWallet";
import { extractAddress } from "@/lib/trade/pasteAddress";

/**
 * Custom wallets on the Scout board (contract v15): the "Add wallet" box,
 * the Custom badge and the remove control. A custom wallet is any address
 * the user added by hand; it is scored and simmed like a leaderboard
 * wallet and stays on the board through refreshes until removed.
 */

export const CUSTOM_HINT = "Added by hand. Scored and simmed like every leaderboard wallet, kept on the board through refreshes.";

export function CustomBadge({ className }: { className?: string }) {
  return (
    <Badge title={CUSTOM_HINT} className={className}>
      Custom
    </Badge>
  );
}

/** Icon button: takes a custom wallet off the board (DELETE /api/scout/custom/{address}). */
export function RemoveCustomButton({
  address,
  onRemove,
  pending,
  className,
}: {
  address: string;
  onRemove: (address: string) => void;
  pending?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-label={`Remove ${shortAddr(address)} from Scout`}
      title="Remove from Scout"
      disabled={pending}
      onClick={() => onRemove(address)}
      className={clsx(
        "grid h-6 w-6 flex-shrink-0 place-items-center rounded-sm border border-border text-muted transition-colors duration-[var(--dur-fast)]",
        "hover:border-border-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
    >
      {pending ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <X size={12} aria-hidden="true" />}
    </button>
  );
}

/**
 * Paste any 0x address (or an explorer link to one) and Add. Validation is
 * lib/scout/addWallet.ts; the parent runs the request and the navigation.
 */
export function AddWalletBox({
  onAdd,
  pending,
  error,
  className,
}: {
  onAdd: (address: string) => void;
  pending: boolean;
  /** The request's error, shown under the box. */
  error?: string | null;
  className?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const message = localError ?? error ?? null;
  const errId = `${id}-error`;

  function submit() {
    const parsed = parseWalletInput(draft);
    if (parsed.address === undefined) {
      setLocalError(parsed.error);
      return;
    }
    setLocalError(null);
    onAdd(parsed.address);
  }

  function onPaste(e: ClipboardEvent<HTMLInputElement>) {
    const a = extractAddress(e.clipboardData.getData("text"));
    if (!a) return;
    e.preventDefault();
    setDraft(a);
    setLocalError(null);
  }

  return (
    <form
      className={clsx("flex flex-col gap-1", className)}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="flex items-center gap-2">
        <Input
          id={id}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (localError) setLocalError(null);
          }}
          onPaste={onPaste}
          placeholder="Paste any 0x address"
          aria-label="Add a wallet to Scout"
          aria-describedby={message ? errId : undefined}
          invalid={Boolean(message)}
          disabled={pending}
          autoComplete="off"
          spellCheck={false}
          leading={<Plus size={13} aria-hidden="true" />}
          className="font-num min-w-0 flex-1 text-xs sm:w-64 sm:flex-none"
        />
        <Button type="submit" size="sm" variant="secondary" disabled={pending} className="flex-shrink-0">
          {pending ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : null}
          Add
        </Button>
      </div>
      {message ? (
        <p id={errId} role="alert" className="text-[11px] text-danger">
          {message}
        </p>
      ) : null}
    </form>
  );
}
