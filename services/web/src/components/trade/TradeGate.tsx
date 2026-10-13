"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { useAuth } from "@/context/AuthContext";
import { TokenWhereToFind } from "@/components/RequireToken";
import { Button, buttonClass } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import type { DemoAccount } from "@/lib/trade/fixtures";

/** No token (or a rejected one): explain, offer the drawer, and offer the demo. */
export function TradeGate({ unauthorized }: { unauthorized: boolean }) {
  const { openDrawer } = useAuth();
  return (
    <div className="mx-auto mt-16 max-w-md">
      <Panel className="p-6 text-center">
        <h1 className="text-title">{unauthorized ? "Token rejected" : "Connect copycat"}</h1>
        <p className="mt-2 text-sm text-muted">
          {unauthorized
            ? "The api rejected the stored token (401). It may have been regenerated: paste the current one."
            : "The Trade page needs your api's bearer token to read your account and place copies."}
        </p>
        <TokenWhereToFind />
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="primary" onClick={openDrawer}>Enter token</Button>
          <Link href="/?demo=1" className={buttonClass("secondary")}>
            Try the demo
          </Link>
        </div>
      </Panel>
    </div>
  );
}

const ACCTS: DemoAccount[] = ["small", "default", "large"];
// Fixed strings, not Intl compact: server and browser ICU disagree ("$20" vs "$20.0") and break hydration.
const ACCT_LABEL: Record<DemoAccount, string> = { small: "$20", default: "$1K", large: "$1M" };

/**
 * Demo only: the sample account size ($20 / $1K / $1M), so both extremes are
 * one click away. The demo strip itself is global (components/DemoStrip.tsx).
 */
export function DemoAccountSwitch({ acct, hrefFor }: { acct: DemoAccount; hrefFor: (a: DemoAccount) => string }) {
  return (
    <nav aria-label="Demo account size" className="flex items-center gap-2 text-xs text-muted">
      <span>Demo account</span>
      <span className="flex rounded-sm border border-border bg-surface-2 p-0.5">
        {ACCTS.map((a) => (
          <Link
            key={a}
            href={hrefFor(a)}
            scroll={false}
            aria-current={a === acct ? "true" : undefined}
            className={clsx(
              "num-sm rounded-sm px-2.5 py-0.5 transition-colors duration-[var(--dur-fast)]",
              a === acct ? "bg-surface text-fg shadow-e1 dark:bg-surface-3" : "hover:text-fg",
            )}
          >
            {ACCT_LABEL[a]}
          </Link>
        ))}
      </span>
    </nav>
  );
}
