"use client";

import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { CopyFitMeter } from "@/components/scout/CopyFitMeter";
import { AddToBookButton, scoutHref, StyleTag } from "@/components/scout/bits";
import { CustomBadge } from "@/components/scout/custom";
import type { ScoutBook } from "@/hooks/useScout";
import { explorerUrl } from "@/lib/address";
import { formatAgo, formatUsd } from "@/lib/format";
import { biasLabel, flagText, flagTone, PNL_TIER_META, SIZE_TIER_HINT, visibleFlags } from "@/lib/scout/labels";
import type { TraderProfile } from "@/lib/scout/types";

/** v15: the file's custom-wallet state and actions (TraderFile wires the hooks). */
export interface CustomActions {
  isCustom: boolean;
  pending: boolean;
  onAdd: () => void;
  onRemove: () => void;
}

export function FileHeader({
  profile,
  book,
  demo,
  nowMs,
  custom,
}: {
  profile: TraderProfile;
  book: ScoutBook;
  demo: boolean;
  nowMs: number;
  custom?: CustomActions;
}) {
  const { row, account, positions_as_of_ms } = profile;
  const inBook = book.inBook(row.address);
  return (
    <div className="flex flex-col gap-3">
      <Link href={scoutHref("/scout", demo)} className="inline-flex w-fit items-center gap-1 text-xs text-muted hover:text-foreground">
        <ArrowLeft size={13} aria-hidden="true" /> Scout board
      </Link>
      <Panel className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {row.display_name ? <h1 className="text-lg font-semibold">{row.display_name}</h1> : <h1 className="sr-only">Trader {row.address}</h1>}
            <AddressChip address={row.address} strong={!row.display_name} />
            {inBook ? <Badge tone="success">Copying</Badge> : null}
            {custom?.isCustom ? <CustomBadge /> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <StyleTag style={row.style} />
            <span title={SIZE_TIER_HINT[row.size_tier]} className="rounded-md border border-border px-1.5 py-0.5 text-[11px]">
              size {row.size_tier}
            </span>
            <span title={PNL_TIER_META[row.pnl_tier].hint} className="rounded-md border border-border px-1.5 py-0.5 text-[11px]">
              {PNL_TIER_META[row.pnl_tier].label}
            </span>
            <span>{biasLabel(account.long_bias_pct)}</span>
            <span>· last active {row.last_fill_ms ? formatAgo(row.last_fill_ms, nowMs) : "unknown"}</span>
            <span title="Leverage, margin and position snapshot below: refreshed every few hours, not every pass. PnL and trade stats above update every pass.">
              · account as of {formatAgo(positions_as_of_ms, nowMs)}
            </span>
          </div>
          {(() => {
            // The 10k-fills note is dropped here (visibleFlags): Copy Fit's
            // own breakdown already states it as a non-binding cap, so
            // showing it again as a second pill is just repetition.
            const flags = visibleFlags(row.flags);
            return flags.length ? (
              <div className="flex flex-wrap gap-1">
                {flags.map((f) => (
                  <Badge key={f} tone={flagTone(f)} title={flagTone(f) === "neutral" ? undefined : "Weighs on whether to trust or copy this trader"}>
                    {flagText(f)}
                  </Badge>
                ))}
              </div>
            ) : null;
          })()}
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div>
            <div className="text-[11px] text-muted">Account value</div>
            <div className="font-num text-xl font-semibold">{formatUsd(row.account_value_usd, true)}</div>
          </div>
          <div>
            <div className="text-[11px] text-muted">Copy Fit</div>
            <CopyFitMeter fit={row.score.copy_fit} size="lg" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <AddToBookButton address={row.address} book={book} inBook={inBook} size="md" />
            {custom ? (
              custom.isCustom ? (
                <Button size="md" variant="secondary" onClick={custom.onRemove} disabled={custom.pending} title="Takes this wallet off the Scout board. Its cached data stays.">
                  Remove from Scout
                </Button>
              ) : (
                <Button
                  size="md"
                  variant="secondary"
                  onClick={custom.onAdd}
                  disabled={custom.pending}
                  title="Keeps this wallet ranked on the Scout board through refreshes, even when it is not in the top 300."
                >
                  Add to Scout board
                </Button>
              )
            ) : null}
            <a
              href={explorerUrl(row.address)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-foreground"
            >
              Explorer <ExternalLink size={13} aria-hidden="true" />
            </a>
          </div>
        </div>
      </Panel>
      {book.addError ? <p className="text-xs text-danger">{book.addError.message}</p> : null}
    </div>
  );
}
