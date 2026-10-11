"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { FlaskConical } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { TokenWhereToFind } from "@/components/RequireToken";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import type { DemoAccount } from "@/lib/trade/fixtures";

/** No token (or a rejected one): explain, offer the drawer, and offer the demo. */
export function TradeGate({ unauthorized }: { unauthorized: boolean }) {
  const { openDrawer } = useAuth();
  return (
    <div className="mx-auto mt-16 max-w-md">
      <Panel className="p-6 text-center">
        <h1 className="text-base font-semibold">{unauthorized ? "Token rejected" : "Connect copycat"}</h1>
        <p className="mt-2 text-sm text-muted">
          {unauthorized
            ? "The api rejected the stored token (401). It may have been regenerated: paste the current one."
            : "The Trade page needs your api's bearer token to read your account and place copies."}
        </p>
        <TokenWhereToFind />
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="primary" onClick={openDrawer}>Enter token</Button>
          <Link href="/?demo=1" className="inline-flex items-center rounded-lg border border-border px-3.5 py-2 text-sm font-medium hover:bg-surface-2">
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

/** Demo strip with the account-size switch ($20 / $1,000 / $1M) so both extremes are one click away. */
export function TradeDemoBanner({ acct, hrefFor }: { acct: DemoAccount; hrefFor: (a: DemoAccount) => string }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-accent/40 bg-accent-soft/40 px-3 py-1.5 text-xs text-muted">
      <FlaskConical size={13} className="text-accent" aria-hidden="true" />
      <span>
        <span className="font-semibold text-foreground">Demo.</span> Sample traders and in-memory copies: nothing leaves this tab.
      </span>
      <span className="ml-auto flex items-center gap-1">
        Account:
        {ACCTS.map((a) => (
          <Link
            key={a}
            href={hrefFor(a)}
            scroll={false}
            className={clsx("font-num rounded px-1.5 py-0.5", a === acct ? "bg-accent text-accent-foreground" : "hover:text-foreground")}
          >
            {ACCT_LABEL[a]}
          </Link>
        ))}
      </span>
    </div>
  );
}
