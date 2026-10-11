import Link from "next/link";
import { Settings as SettingsIcon } from "lucide-react";
import { globalSummary } from "@/lib/trade/globalSummary";
import type { TradeSettings } from "@/lib/trade/types";

/** "Use global": read-only Settings tab values that will apply, with a way to change them. */
export function GlobalSummary({ settings, settingsHref, supported }: { settings: TradeSettings | undefined; settingsHref: string; supported: boolean }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2/50 p-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium text-foreground">Your Settings tab applies</span>
        <Link href={settingsHref} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
          <SettingsIcon size={12} aria-hidden="true" /> Edit in Settings
        </Link>
      </div>
      {settings ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {globalSummary(settings).map((r) => (
            <div key={r.label} className="contents">
              <dt className="text-muted">{r.label}</dt>
              <dd className="font-num text-right text-foreground">{r.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="h-24 animate-pulse rounded bg-surface-2" />
      )}
      <p className="text-[11px] text-muted">Change Settings later and this wallet follows.</p>
      {!supported ? <p className="text-[11px] text-warning">Your api predates global copying (contract v7). Use Custom, or update services/api.</p> : null}
    </div>
  );
}
