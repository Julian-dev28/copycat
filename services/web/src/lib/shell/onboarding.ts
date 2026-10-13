/**
 * First-run checklist (token, account, deposit, pick a trader, go live). Pure:
 * real app state in, which steps are done out. The panel (OnboardingChecklist.tsx)
 * renders this and disappears once every step is done.
 */
import type { NavHref } from "./nav";

export interface OnboardingState {
  hasToken: boolean;
  hasActiveAccount: boolean;
  /** null while unknown (not loaded yet, or no active account): never counted as done. */
  equityUsd: number | null;
  /** Traders copied (settings/engine-status "leaders"). */
  walletsInBook: number;
  /** enabled && !dry_run. */
  tradingLive: boolean;
}

export interface OnboardingStep {
  key: "token" | "account" | "deposit" | "wallet" | "live";
  label: string;
  done: boolean;
  /** Page to jump to. The token step has none: it opens the token drawer instead. */
  href: NavHref | null;
}

export function onboardingSteps(s: OnboardingState): OnboardingStep[] {
  return [
    { key: "token", label: "Set your API token", done: s.hasToken, href: null },
    { key: "account", label: "Create or connect a trading account", done: s.hasActiveAccount, href: "/account" },
    { key: "deposit", label: "Deposit funds", done: (s.equityUsd ?? 0) > 0, href: "/account" },
    { key: "wallet", label: "Pick a trader to copy", done: s.walletsInBook > 0, href: "/" },
    { key: "live", label: "Go live: turn trading on, dry run off", done: s.tradingLive, href: "/settings" },
  ];
}

export function onboardingComplete(steps: OnboardingStep[]): boolean {
  return steps.every((s) => s.done);
}
