"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Check, KeyRound } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useActiveAccount } from "@/components/account/hooks";
import { NOT_A_VAULT_TEXT } from "@/components/account/bits";
import { onboardingComplete, onboardingSteps, type OnboardingStep } from "@/lib/shell/onboarding";
import { useDemoQuery, useMounted } from "./useDemoQuery";

/**
 * First-run checklist: token, account, deposit, pick a trader, go live. Real
 * state only (lib/shell/onboarding.ts), no manual dismiss: it disappears the
 * moment every step is actually done, and comes back if one regresses (e.g.
 * equity drops back to zero) so the user is never left guessing why trading
 * stopped. Off in demo (its own strip already explains the demo book) and on
 * Scout (research, not setup).
 *
 * Renders nothing until mounted: every input (the stored token, account and
 * engine-status queries) is unknown during SSR and the first client paint,
 * so rendering real checklist state before then would hydration-mismatch.
 */
export function OnboardingChecklist() {
  const pathname = usePathname();
  const mounted = useMounted();
  const demo = Boolean(useDemoQuery());
  const { hasToken, openDrawer } = useAuth();
  const accounts = useActiveAccount();
  const status = useEngineStatus();

  if (!mounted || demo || pathname?.startsWith("/scout")) return null;

  const steps = onboardingSteps({
    hasToken,
    hasActiveAccount: Boolean(accounts.active),
    equityUsd: status.data?.equity_usd ?? null,
    walletsInBook: status.data?.leaders.length ?? 0,
    tradingLive: Boolean(status.data?.enabled && !status.data?.dry_run),
  });
  if (onboardingComplete(steps)) return null;

  return (
    <section aria-label="First-run checklist" className="mb-4 flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 shadow-e1">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6 sm:gap-y-2">
        <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Get set up</h2>
        <ol className="flex flex-1 flex-wrap gap-x-6 gap-y-2">
          {steps.map((s) => (
            <ChecklistItem key={s.key} step={s} onToken={openDrawer} />
          ))}
        </ol>
      </div>
      {/* research/user_consensus_2026-10.md: a copier can confuse the copy-sim
          with a real HL vault (lockup, profit share). Say plainly it's neither. */}
      <p className="text-[11px] text-muted">{NOT_A_VAULT_TEXT}</p>
    </section>
  );
}

function ChecklistItem({ step, onToken }: { step: OnboardingStep; onToken: () => void }) {
  const body = (
    <>
      <span
        className={`grid h-5 w-5 flex-shrink-0 place-items-center rounded-sm border text-[10px] ${
          step.done ? "border-success bg-success/15 text-success" : "border-border text-muted"
        }`}
        aria-hidden="true"
      >
        {step.done ? <Check size={12} /> : null}
      </span>
      <span className={step.done ? "text-muted line-through" : "text-fg"}>{step.label}</span>
    </>
  );
  const className = "flex items-center gap-2 text-sm";
  if (step.done) return <li className={className}>{body}</li>;
  if (!step.href) {
    return (
      <li>
        <button type="button" onClick={onToken} className={`${className} hover:text-accent`}>
          {body}
          <KeyRound size={13} className="text-muted" aria-hidden="true" />
        </button>
      </li>
    );
  }
  return (
    <li>
      <Link href={step.href} className={`${className} hover:text-accent`}>
        {body}
      </Link>
    </li>
  );
}
