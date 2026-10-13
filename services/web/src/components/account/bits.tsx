"use client";

import { clsx } from "clsx";
import { Check, Copy, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { agentView, KIND_META, type AgentTone } from "@/lib/account/agent";
import { copySecret } from "@/lib/account/secrets";
import type { TradingAccount } from "@/lib/account/types";

const DOT: Record<AgentTone, string> = { success: "bg-success", warning: "bg-warning", danger: "bg-danger", neutral: "bg-muted" };

export function AgentDot({ account, nowMs, className }: { account: TradingAccount; nowMs: number; className?: string }) {
  const v = agentView(account, nowMs);
  return <span className={clsx("inline-block h-2 w-2 flex-shrink-0 rounded-full", DOT[v.tone], className)} title={`Trading agent: ${v.label}`} aria-hidden="true" />;
}

export function AgentBadge({ account, nowMs }: { account: TradingAccount; nowMs: number }) {
  const v = agentView(account, nowMs);
  return (
    <span title={v.hint ?? "The trading agent can place orders for this account."}>
      <Badge tone={v.tone === "neutral" ? "neutral" : v.tone}>
        <span className={clsx("h-1.5 w-1.5 rounded-full", DOT[v.tone])} aria-hidden="true" />
        Agent {v.label.toLowerCase()}
      </Badge>
    </span>
  );
}

export function KindBadge({ kind }: { kind: TradingAccount["kind"] }) {
  return (
    <span title={KIND_META[kind].hint}>
      <Badge tone={kind === "created" ? "accent" : "neutral"}>{KIND_META[kind].label}</Badge>
    </span>
  );
}

/** copycat vs. a real HL vault (research/user_consensus_2026-10.md: "Known ways copiers lose
 * money" - vault lockup/profit-share confusion). Exported so a test can pin the facts without
 * rendering JSX. */
export const NOT_A_VAULT_TEXT =
  "This is your own Hyperliquid account, not a pooled vault: no lockup, no profit share, nothing deposited with anyone else. Copying places the same trades on your account, with your own money.";

/** What an agent key can and cannot do. Shown wherever a key is handed over. */
export function AgentBanner({ compact }: { compact?: boolean }) {
  return (
    <div className="flex gap-2.5 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2.5 text-xs">
      <ShieldCheck size={16} className="mt-0.5 flex-shrink-0 text-accent" aria-hidden="true" />
      <div className="text-muted">
        <p className="font-semibold text-foreground">copycat trades with an agent key: it can trade, it cannot withdraw.</p>
        {compact ? null : (
          <>
            <p className="mt-0.5">
              Hyperliquid agent wallets can place and cancel orders only. Moving funds out always needs the main wallet. Keys never leave this machine.
            </p>
            <p className="mt-0.5">{NOT_A_VAULT_TEXT}</p>
          </>
        )}
      </div>
    </div>
  );
}

/** Password-style input for keys and passphrases: no autofill, no spellcheck, optional peek. */
export function SecretInput({ peek = true, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { peek?: boolean }) {
  const [shown, setShown] = useState(false);
  return (
    <div className={clsx("relative", className)}>
      <input
        {...rest}
        type={shown ? "text" : "password"}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        className="w-full rounded-lg border border-border bg-surface-2 py-2 pr-9 pl-3 font-num text-sm text-foreground placeholder:font-sans placeholder:text-muted focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]"
      />
      {peek ? (
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? "Hide" : "Show"}
          className="absolute inset-y-0 right-1 my-auto h-7 rounded-md px-1.5 text-muted hover:text-foreground"
        >
          {shown ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      ) : null}
    </div>
  );
}

/** Copy button. `secret` wipes the clipboard after 60s (see lib/account/secrets). */
export function CopyButton({ text, label, secret, className }: { text: string; label: string; secret?: boolean; className?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const cancelClear = useRef<(() => void) | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      cancelClear.current?.();
      if (secret) cancelClear.current = await copySecret(text);
      else await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }

  return (
    <button
      type="button"
      onClick={copy}
      className={clsx("inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs font-medium hover:bg-border", className)}
    >
      {state === "copied" ? <Check size={13} className="text-success" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
      {state === "copied" ? (secret ? "Copied, clears in 60s" : "Copied") : state === "failed" ? "Copy blocked" : label}
      <span role="status" className="sr-only">{state === "copied" ? "Copied" : ""}</span>
    </button>
  );
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">{label}</label>
      {children}
      {hint ? <div className="text-[11px] text-muted">{hint}</div> : null}
    </div>
  );
}

export function ErrorLine({ children }: { children: ReactNode }) {
  if (!children) return null;
  return <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">{children}</p>;
}
