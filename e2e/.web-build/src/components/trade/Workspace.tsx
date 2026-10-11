"use client";

import { Loader2 } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { useScoutProfile } from "@/hooks/useScout";
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

/** The center column (header, chart, his book) and the ticket for one wallet. Keyed by address. */
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
}) {
  const { demo } = useTradeMode();
  const prof = useScoutProfile(address);
  const profile = prof.data?.kind === "ready" ? prof.data.profile : undefined;
  const t = useTicket(address, profile, settings, status, wallet);
  const fileHref = withDemo(`/scout/${address}`, demo);
  const theRow = profile?.row ?? row;

  return (
    <>
      <Panel className="flex min-w-0 flex-col gap-4 p-4">
        <WalletHeader address={address} row={theRow} nowMs={nowMs} fileHref={fileHref} inBook={inBook} onScout={row !== null} />
        {profile ? (
          <>
            <IndexChart profile={profile} direction={t.eff.direction} />
            <WalletTabs profile={profile} preview={t.draft.source === "global" || t.amount ? t.preview : null} fileHref={fileHref} nowMs={nowMs} />
          </>
        ) : prof.data?.kind === "building" ? (
          <p className="flex items-center gap-2 py-16 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Building this wallet&apos;s file from Hyperliquid. Usually under a minute.
          </p>
        ) : prof.error && row === null && apiProblem(prof.error) === "too_old" ? (
          <p className="py-16 text-center text-sm text-muted">
            Scout has no file for this wallet yet, so there is no chart. The ticket still previews what you would copy from their live positions.
          </p>
        ) : prof.error ? (
          <p className="py-16 text-center text-sm text-danger">{problemText(prof.error, "trader file")}</p>
        ) : (
          <div className="h-[340px] animate-pulse rounded-lg bg-surface-2" aria-label="Loading wallet" />
        )}
      </Panel>
      <div id="ticket" className="scroll-mt-20 md:col-start-2 xl:sticky xl:top-20 xl:col-start-3 xl:row-start-1 xl:max-h-[calc(100vh-6.5rem)] xl:self-start xl:overflow-y-auto">
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
        />
      </div>
    </>
  );
}
