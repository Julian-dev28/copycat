"use client";

import { Loader2 } from "lucide-react";
import { EmptyState, Panel, Skeleton } from "@/components/ui";
import { useScoutProfile } from "@/hooks/useScout";
import type { CopyPosition } from "@/lib/api/types";
import { apiProblem, problemText } from "@/lib/trade/apiState";
import type { TraderRow } from "@/lib/scout/types";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import { IndexChart } from "./IndexChart";
import { Ticket } from "./Ticket";
import { WalletHeader } from "./WalletHeader";
import { WalletTabs } from "./WalletTabs";
import { useTicket } from "./useTicket";
import { useTradeMode } from "./hooks";
import { withDemo } from "./bits";

/**
 * The center column (header, chart, their positions) and the ticket for one
 * trader. Keyed by address. The ticket is a sticky rail from 1024px up and a
 * bottom sheet below that (Ticket.tsx).
 */
export function Workspace({
  address,
  row,
  settings,
  status,
  wallet,
  inBook,
  nowMs,
  settingsHref,
  allCoins,
  sheetOpen,
  onSheet,
}: {
  address: string;
  row: TraderRow | null;
  settings: TradeSettings | undefined;
  status: TradeStatus | undefined;
  wallet: WalletPosition | null;
  inBook: boolean;
  nowMs: number;
  settingsHref: string;
  allCoins: string[];
  sheetOpen: boolean;
  onSheet: (open: boolean) => void;
}) {
  const { demo } = useTradeMode();
  const prof = useScoutProfile(address);
  const profile = prof.data?.kind === "ready" ? prof.data.profile : undefined;
  const t = useTicket(address, profile, settings, status, wallet);
  const fileHref = withDemo(`/scout/${address}`, demo);
  const theRow = profile?.row ?? row;
  const held = new Map<string, CopyPosition>((status?.positions ?? []).filter((c) => c.leader === address).map((c) => [c.coin, c]));

  return (
    <>
      <Panel enter={1} className="flex min-w-0 flex-col gap-4 p-4 sm:p-5 lg:col-start-2 lg:row-start-1">
        <WalletHeader address={address} row={theRow} nowMs={nowMs} fileHref={fileHref} inBook={inBook} onScout={row !== null} />
        {profile ? (
          <>
            <IndexChart profile={profile} direction={t.eff.direction} />
            <WalletTabs
              profile={profile}
              preview={t.draft.source === "global" || t.amount ? t.preview : null}
              fileHref={fileHref}
              nowMs={nowMs}
              invested={t.invested}
              held={held}
            />
          </>
        ) : prof.data?.kind === "building" ? (
          <p className="flex items-center gap-2 py-16 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Building this trader&apos;s file from Hyperliquid. Usually under a minute.
          </p>
        ) : prof.error && row === null && apiProblem(prof.error) === "too_old" ? (
          <EmptyState
            compact
            title={
              <>
                No chart <em>yet</em>
              </>
            }
            body="Scout has no file for this trader yet. The ticket still previews what you would copy from their live positions."
          />
        ) : prof.error ? (
          <p role="alert" className="py-16 text-center text-sm text-danger">
            {problemText(prof.error, "trader file")}
          </p>
        ) : (
          <div role="status" aria-label="Loading trader" className="flex flex-col gap-3">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-[240px] w-full" />
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
      </Panel>
      <div
        id="ticket"
        className={
          "scroll-mt-20 " +
          // 1024px+: a sticky rail with its own height; the ticket's action bar pins to its bottom
          "lg:sticky lg:top-24 lg:col-start-3 lg:row-start-1 lg:flex lg:max-h-[calc(100dvh-7.5rem)] lg:flex-col lg:self-start " +
          // under 1024px: a bottom sheet above the tab bar (the tab bar shows under 640px only)
          "max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-30 max-sm:bottom-[calc(var(--tabbar-h)+env(safe-area-inset-bottom))]"
        }
      >
        <Ticket
          address={address}
          name={theRow?.display_name ?? null}
          t={t}
          settings={settings}
          status={status}
          wallet={wallet}
          settingsHref={settingsHref}
          nowMs={nowMs}
          profile={profile}
          row={theRow}
          allCoins={allCoins}
          sheetOpen={sheetOpen}
          onSheet={onSheet}
        />
      </div>
    </>
  );
}
