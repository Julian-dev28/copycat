"use client";

import { useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { ArrowUpRight } from "lucide-react";
import { CoinBadge } from "@/components/scout/bits";
import { Badge, EmptyState, InfoTip, Pnl, TABLE, TableScroll, TabPanel, Tabs } from "@/components/ui";
import { useFlashOnChange } from "@/hooks/useFlashOnChange";
import { formatAgo, formatPct, formatPrice, formatSignedPct, formatSignedUsd, formatUsd } from "@/lib/format";
import type { TraderProfile } from "@/lib/scout/types";
import type { CopyPosition } from "@/lib/api/types";
import type { PlannedCopy, TicketPreview } from "@/lib/trade/ticket";
import { COPY_ROW_LABEL, copyColumnTitle, copyRowState, skipReasonShort, type CopyRowState } from "@/lib/trade/ticketView";
import { SideTag } from "./bits";

type Tab = "positions" | "trades" | "strategy";

/**
 * The trader's positions, trades and a pointer to their Strategy. The copy
 * column says what is real: "held" (your money is in it), "next trade" (you
 * copy them but hold none of this coin) or "would copy" (you don't copy them).
 * Engine numbers render plainly; a local estimate is muted and tagged.
 */
export function WalletTabs({
  profile,
  preview,
  fileHref,
  nowMs,
  invested,
  held,
}: {
  profile: TraderProfile;
  preview: TicketPreview | null;
  fileHref: string;
  nowMs: number;
  /** You copy this trader now. */
  invested: boolean;
  /** Your open copies of this trader, by coin. */
  held: ReadonlyMap<string, CopyPosition>;
}) {
  const [tab, setTab] = useState<Tab>("positions");
  const idBase = "wallet-tabs";
  return (
    <div className="flex flex-col">
      <Tabs
        aria-label="Trader details"
        idBase={idBase}
        value={tab}
        onChange={setTab}
        items={[
          { id: "positions", label: "Their positions", count: profile.positions.length },
          { id: "trades", label: "Their trades" },
          { id: "strategy", label: "Strategy" },
        ]}
      />
      <TabPanel idBase={idBase} id={tab}>
        {tab === "positions" ? <Positions profile={profile} preview={preview} invested={invested} held={held} /> : null}
        {tab === "trades" ? <Trades profile={profile} nowMs={nowMs} /> : null}
        {tab === "strategy" ? (
          <div className="flex flex-col items-start gap-2 p-4 text-sm">
            <p className="text-muted">
              What they trade, when, how long they hold and how they size in: the Strategy tab of their trader file breaks it down with examples.
            </p>
            <Link href={fileHref} className="group inline-flex items-center gap-1 font-medium text-accent hover:underline">
              Open their trader file{" "}
              <ArrowUpRight size={14} aria-hidden="true" className="transition-transform duration-[var(--dur-fast)] group-hover:translate-x-0.5" />
            </Link>
          </div>
        ) : null}
      </TabPanel>
    </div>
  );
}

/** One cell of the copy column: real money plainly, a plan muted, an estimate tagged. */
function CopyCell({
  state,
  copy,
  mine,
  source,
  hasPreview,
}: {
  state: CopyRowState;
  copy: PlannedCopy | undefined;
  mine: CopyPosition | undefined;
  source: TicketPreview["source"] | null;
  hasPreview: boolean;
}) {
  if (state === "held" && mine) {
    const usd = Math.abs(mine.notional_usd);
    return (
      <span className="inline-flex items-center gap-1.5" data-copy-state="held">
        {copy?.ourSide && copy.ourSide !== copy.side ? <SideTag side={copy.ourSide} /> : null}
        <span className="text-fg">{formatUsd(usd, usd >= 100_000)}</span>
        <span className="num-sm text-muted">{mine.leverage}x</span>
        <Badge tone="accent">{COPY_ROW_LABEL.held}</Badge>
      </span>
    );
  }
  if (!copy) return <span className="text-muted">{hasPreview ? "not copied" : "enter an amount"}</span>;
  if (copy.status === "skipped") {
    return (
      <span className="text-muted" title={copy.reason ?? undefined}>
        {copy.filtered ? "filtered" : skipReasonShort(copy.reason)}
      </span>
    );
  }
  const estimate = source === "local";
  return (
    <span className={clsx("inline-flex items-center gap-1.5", estimate ? "text-muted" : "text-fg-soft")} data-copy-state={state}>
      {copy.ourSide && copy.ourSide !== copy.side ? <SideTag side={copy.ourSide} /> : null}
      <span>{formatUsd(copy.notionalUsd, copy.notionalUsd >= 100_000)}</span>
      <span className="num-sm text-muted">{copy.leverage}x</span>
      {state === "next" ? <Badge tone="neutral">{COPY_ROW_LABEL.next}</Badge> : null}
      {estimate ? (
        <Badge tone="neutral" title="Browser estimate; the engine preview replaces it when it lands">
          estimate
        </Badge>
      ) : null}
    </span>
  );
}

/** Mark price, flashing on each tick (throttled, static tint under reduced motion). */
function MarkCell({ value }: { value: number }) {
  const flash = useFlashOnChange(value);
  return <span className={clsx("rounded-sm px-0.5", flash)}>{formatPrice(value)}</span>;
}

function Positions({
  profile,
  preview,
  invested,
  held,
}: {
  profile: TraderProfile;
  preview: TicketPreview | null;
  invested: boolean;
  held: ReadonlyMap<string, CopyPosition>;
}) {
  if (!profile.positions.length) {
    return (
      <EmptyState
        compact
        title={
          <>
            Flat <em>right now</em>
          </>
        }
        body="Your copies open when they open a position."
      />
    );
  }
  const heldCoins = new Set(held.keys());
  const title = copyColumnTitle(invested);
  const rows = profile.positions.map((p) => ({
    p,
    copy: preview?.copies.find((x) => x.coin === p.coin),
    mine: held.get(p.coin),
    state: copyRowState(invested, heldCoins, p.coin),
  }));
  const cell = (r: (typeof rows)[number]) => (
    <CopyCell state={r.state} copy={r.copy} mine={r.mine} source={preview?.source ?? null} hasPreview={preview !== null} />
  );
  return (
    <>
      {/* phones: stacked cards (the table has more than 5 columns) */}
      <ul className="flex flex-col divide-y divide-border sm:hidden" aria-label="Their positions">
        {rows.map((r) => (
          <li key={r.p.coin} className="flex flex-col gap-2 py-3">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <CoinBadge coin={r.p.coin} />
                <SideTag side={r.p.side} />
                <span className="num-sm text-muted">
                  {r.p.leverage}x {r.p.is_cross ? "cross" : "iso"}
                </span>
              </span>
              <Pnl value={r.p.unrealized_pnl_usd} className="num" />
            </div>
            <dl className="num grid grid-cols-2 gap-x-4 gap-y-1 text-fg-soft">
              <KV k="Notional">{formatUsd(r.p.notional_usd, true)}</KV>
              <KV k="Mark">
                <MarkCell value={r.p.mark_px} />
              </KV>
              <KV k="Entry">{formatPrice(r.p.entry_px)}</KV>
              <KV k="To liq">{formatPct(r.p.liq_distance_pct)}</KV>
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-label text-muted">{title}</span>
              <span className="num">{cell(r)}</span>
            </div>
          </li>
        ))}
      </ul>
      <TableScroll label="Their positions" className="hidden sm:block">
        <table className={TABLE.table}>
          <thead>
            <tr>
              <th scope="col" className={clsx(TABLE.th, "left-0 z-[3]")}>Coin</th>
              <th scope="col" className={TABLE.th}>
                <span className="inline-flex items-center gap-1">
                  {title}
                  <InfoTip
                    id="copy-col-tip"
                    label={`About ${title}`}
                    content={
                      invested
                        ? "held: you hold this copy now. next trade: you hold none of it; this size applies when they trade it next."
                        : "What a copy would open with the ticket's terms. Nothing is invested yet."
                    }
                  />
                </span>
              </th>
              <th scope="col" className={TABLE.thNum}>Lev</th>
              <th scope="col" className={TABLE.thNum}>Notional</th>
              <th scope="col" className={TABLE.thNum}>Entry</th>
              <th scope="col" className={TABLE.thNum}>Mark</th>
              <th scope="col" className={TABLE.thNum}>uPnL (ROE)</th>
              <th scope="col" className={TABLE.thNum}>To liq</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.p.coin} className={TABLE.tr}>
                <td className={clsx(TABLE.td, TABLE.stickyFirst)}>
                  <span className="flex items-center gap-1.5">
                    <CoinBadge coin={r.p.coin} />
                    <SideTag side={r.p.side} />
                  </span>
                </td>
                <td className={clsx(TABLE.td, "num")}>{cell(r)}</td>
                <td className={TABLE.tdNum}>
                  {r.p.leverage}x <span className="num-sm text-muted">{r.p.is_cross ? "cross" : "iso"}</span>
                </td>
                <td className={TABLE.tdNum}>{formatUsd(r.p.notional_usd, true)}</td>
                <td className={TABLE.tdNum}>{formatPrice(r.p.entry_px)}</td>
                <td className={TABLE.tdNum}>
                  <MarkCell value={r.p.mark_px} />
                </td>
                <td className={TABLE.tdNum}>
                  <Pnl value={r.p.unrealized_pnl_usd} />{" "}
                  <Pnl value={r.p.roe_pct} className="num-sm">
                    ({formatSignedPct(r.p.roe_pct)})
                  </Pnl>
                </td>
                <td className={TABLE.tdNum}>{formatPct(r.p.liq_distance_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </>
  );
}

function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-label text-muted">{k}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Trades({ profile, nowMs }: { profile: TraderProfile; nowMs: number }) {
  const fills = profile.recent_fills.slice(0, 40);
  if (!fills.length) {
    return (
      <EmptyState
        compact
        title={
          <>
            No trades <em>lately</em>
          </>
        }
        body="Nothing in the last 30 days."
      />
    );
  }
  return (
    <TableScroll label="Their trades">
      <table className={TABLE.table}>
        <thead>
          <tr>
            <th scope="col" className={TABLE.th}>Time</th>
            <th scope="col" className={TABLE.th}>Coin</th>
            <th scope="col" className={TABLE.th}>Action</th>
            <th scope="col" className={TABLE.thNum}>Price</th>
            <th scope="col" className={TABLE.thNum}>Size</th>
            <th scope="col" className={TABLE.thNum}>Closed PnL</th>
          </tr>
        </thead>
        <tbody>
          {fills.map((f, i) => (
            <tr key={`${f.time_ms}-${i}`} className={TABLE.tr}>
              <td className={clsx(TABLE.td, "num text-muted")}>{formatAgo(f.time_ms, nowMs)}</td>
              <td className={TABLE.td}>
                <CoinBadge coin={f.coin} />
              </td>
              <td className={clsx(TABLE.td, "text-xs font-medium")}>{f.dir}</td>
              <td className={TABLE.tdNum}>{formatPrice(f.px)}</td>
              <td className={TABLE.tdNum}>{formatUsd(f.notional_usd, true)}</td>
              <td className={TABLE.tdNum}>
                {f.closed_pnl_usd ? <Pnl value={f.closed_pnl_usd}>{formatSignedUsd(f.closed_pnl_usd)}</Pnl> : <span className="text-muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
