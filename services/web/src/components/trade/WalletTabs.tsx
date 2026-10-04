"use client";

import { useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { ArrowUpRight } from "lucide-react";
import { CoinBadge } from "@/components/scout/bits";
import { formatAgo, formatPct, formatPrice, formatSignedPct, formatSignedUsd, formatUsd } from "@/lib/format";
import type { TraderProfile } from "@/lib/scout/types";
import type { TicketPreview } from "@/lib/trade/ticket";

type Tab = "positions" | "trades" | "strategy";
const TH = "px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-3 py-2 whitespace-nowrap font-num";

export function WalletTabs({ profile, preview, fileHref, nowMs }: { profile: TraderProfile; preview: TicketPreview | null; fileHref: string; nowMs: number }) {
  const [tab, setTab] = useState<Tab>("positions");
  const tabs: { id: Tab; label: string }[] = [
    { id: "positions", label: `Their positions (${profile.positions.length})` },
    { id: "trades", label: "Their trades" },
    { id: "strategy", label: "Strategy" },
  ];
  return (
    <div className="flex flex-col">
      <div role="tablist" aria-label="Wallet details" className="flex gap-4 overflow-x-auto border-b border-border px-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={clsx("-mb-px whitespace-nowrap border-b-2 px-1 py-2 text-sm", tab === t.id ? "border-accent font-semibold" : "border-transparent text-muted hover:text-foreground")}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="overflow-x-auto">
        {tab === "positions" ? <Positions profile={profile} preview={preview} /> : null}
        {tab === "trades" ? <Trades profile={profile} nowMs={nowMs} /> : null}
        {tab === "strategy" ? (
          <div className="flex flex-col items-start gap-2 p-4 text-sm">
            <p className="text-muted">
              What he trades, when, how long he holds and how he sizes in: the Strategy tab of his trader file breaks it down with
              examples.
            </p>
            <Link href={fileHref} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
              Open his trader file <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Positions({ profile, preview }: { profile: TraderProfile; preview: TicketPreview | null }) {
  if (!profile.positions.length) return <p className="p-4 text-sm text-muted">He&apos;s flat right now. Your copies open when he opens.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border">
          {["Coin", "Your copy", "Lev", "Notional", "Entry", "Mark", "uPnL (ROE)", "To liq"].map((h) => (
            <th key={h} scope="col" className={clsx(TH, h === "Your copy" && "text-accent")}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {profile.positions.map((p) => {
          const c = preview?.copies.find((x) => x.coin === p.coin);
          return (
            <tr key={p.coin} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-2">
                <span className="flex items-center gap-1.5">
                  <CoinBadge coin={p.coin} />
                  <span className={clsx("text-[11px] font-semibold uppercase", p.side === "long" ? "text-success" : "text-danger")}>{p.side}</span>
                </span>
              </td>
              <td className={TD}>
                {!c ? <span className="text-muted">{preview ? "not copied" : "enter an amount"}</span> : c.status === "skipped" ? (
                  <span className="text-warning" title={c.reason ?? undefined}>skipped</span>
                ) : (
                  <span>{formatUsd(c.notionalUsd, c.notionalUsd >= 100_000)} <span className="text-[11px] text-muted">{c.leverage}x</span></span>
                )}
              </td>
              <td className={TD}>{p.leverage}x <span className="text-[11px] text-muted">{p.is_cross ? "cross" : "iso"}</span></td>
              <td className={TD}>{formatUsd(p.notional_usd, true)}</td>
              <td className={TD}>{formatPrice(p.entry_px)}</td>
              <td className={TD}>{formatPrice(p.mark_px)}</td>
              <td className={clsx(TD, p.unrealized_pnl_usd >= 0 ? "text-success" : "text-danger")}>
                {formatSignedUsd(p.unrealized_pnl_usd)} <span className="text-[11px]">({formatSignedPct(p.roe_pct)})</span>
              </td>
              <td className={TD}>{formatPct(p.liq_distance_pct)}</td>

            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Trades({ profile, nowMs }: { profile: TraderProfile; nowMs: number }) {
  const fills = profile.recent_fills.slice(0, 40);
  if (!fills.length) return <p className="p-4 text-sm text-muted">No trades in the last 30 days.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border">
          {["Time", "Coin", "Action", "Price", "Size", "Closed PnL"].map((h) => <th key={h} scope="col" className={TH}>{h}</th>)}
        </tr>
      </thead>
      <tbody>
        {fills.map((f, i) => (
          <tr key={`${f.time_ms}-${i}`} className="border-b border-border/60 last:border-0">
            <td className={clsx(TD, "text-muted")}>{formatAgo(f.time_ms, nowMs)}</td>
            <td className="px-3 py-2"><CoinBadge coin={f.coin} /></td>
            <td className={clsx("whitespace-nowrap px-3 py-2 text-xs font-medium", /Long/.test(f.dir) === /Open/.test(f.dir) ? "text-success" : "text-danger")}>{f.dir}</td>
            <td className={TD}>{formatPrice(f.px)}</td>
            <td className={TD}>{formatUsd(f.notional_usd, true)}</td>
            <td className={clsx(TD, f.closed_pnl_usd > 0 ? "text-success" : f.closed_pnl_usd < 0 ? "text-danger" : "text-muted")}>
              {f.closed_pnl_usd ? formatSignedUsd(f.closed_pnl_usd) : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
