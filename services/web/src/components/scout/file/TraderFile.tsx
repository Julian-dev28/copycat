"use client";

import { useState } from "react";
import { Loader2, SearchX } from "lucide-react";
import { LoadError, PageSkeleton } from "@/components/PageStates";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { ApiTooOld } from "@/components/scout/bits";
import { toast } from "@/components/ui/Toast";
import { useNow } from "@/hooks/useNow";
import { useAddCustomWallet, useRemoveCustomWallet, useScoutBook, useScoutCustom, useScoutMode } from "@/hooks/useScout";
import { normAddr } from "@/lib/address";
import { addedText } from "@/lib/scout/addWallet";
import { buildingText, fileView } from "@/lib/scout/file/state";
import type { WhatIfResult } from "@/lib/scout/types";
import { FileHeader } from "./FileHeader";
import { FileTabs } from "./FileTabs";
import { useFileProfile } from "./hooks";
import { PerformanceChart } from "./PerformanceChart";
import { PnlCalendar } from "./PnlCalendar";
import { StatTiles } from "./StatTiles";
import { TopCoins } from "./TopCoins";
import { TradeBreakdown } from "./TradeBreakdown";
import { WhatIfPanel } from "./WhatIfPanel";

function Message({ title, children, spin }: { title: string; children: React.ReactNode; spin?: boolean }) {
  return (
    <Panel className="flex flex-col items-center gap-2 px-5 py-12 text-center" role="status">
      {spin ? <Loader2 size={26} className="animate-spin text-accent" aria-hidden="true" /> : <SearchX size={26} className="text-muted" aria-hidden="true" />}
      <p className="text-sm font-semibold">{title}</p>
      <div className="max-w-md text-sm text-muted">{children}</div>
    </Panel>
  );
}

export function TraderFile({ address }: { address: string }) {
  const { demo } = useScoutMode();
  const q = useFileProfile(address);
  const book = useScoutBook();
  const nowMs = useNow();
  const customList = useScoutCustom();
  const addCustom = useAddCustomWallet();
  const removeCustom = useRemoveCustomWallet();
  const [whatIf, setWhatIf] = useState<WhatIfResult | null>(null);
  const view = fileView(address, q.data, q.error);

  if (view === "invalid") return <Message title="That is not a wallet address">Trader files take a 0x address with 40 hex characters.</Message>;
  if (view === "too_old") return <ApiTooOld what="the trader file" />;
  if (view === "not_found") return <Message title="No trader file for this address">The api has no Hyperliquid account data for it. Check the address.</Message>;
  if (view === "error") return <LoadError what="the trader file" error={q.error} onRetry={() => q.refetch()} />;
  if (view === "building" && q.data?.kind === "building") {
    const t = buildingText(q.data.status);
    return (
      <Message title="Building this trader file" spin>
        Reading his fills, positions and the copy sim. This page checks back every 3 seconds{t ? ` (${t})` : ""}.
      </Message>
    );
  }
  if (q.data?.kind !== "ready") return <PageSkeleton label="Loading trader file" rows={4} />;

  const base = q.data.profile;
  const profile = whatIf ? { ...base, sim_curve: whatIf.sim_curve } : base;
  // The board row says `custom` once the board was republished with it; the custom list
  // knows right after the add, before that republish. Either means it is custom.
  const a = normAddr(base.row.address);
  const isCustom = Boolean(base.row.custom) || (customList.data ?? []).some((c) => c.address === a);
  const custom = {
    isCustom,
    pending: addCustom.isPending || removeCustom.isPending,
    onAdd: () =>
      addCustom.mutate(a, {
        onSuccess: (res) => toast(addedText(a, res.queued), { tone: "success" }),
        onError: (e) => toast.error(e.message),
      }),
    onRemove: () =>
      removeCustom.mutate(a, {
        onSuccess: () => toast("Removed from Scout"),
        onError: (e) => toast.error(e.message),
      }),
  };

  return (
    <div className="flex flex-col gap-4">
      <FileHeader profile={base} book={book} demo={demo} nowMs={nowMs} custom={custom} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Panel>
            <PanelHeader title="Performance" description="His PnL or account value, with your copy's sim overlaid" />
            <div className="px-4 pb-4">
              <PerformanceChart profile={profile} simLabel={whatIf ? "Your copy (what-if)" : undefined} />
            </div>
          </Panel>
          <StatTiles profile={base} />
          <Panel>
            <PanelHeader title="Daily PnL" description="UTC days" />
            <div className="px-4 pb-4">
              <PnlCalendar daily={base.daily_pnl} />
            </div>
          </Panel>
          <FileTabs profile={base} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <WhatIfPanel address={base.row.address} base={base.row.score} book={book} onResult={setWhatIf} />
          <Panel>
            <PanelHeader title="Top coins" description="30d volume share and PnL" />
            <div className="px-4 pb-4">
              <TopCoins coins={base.coins.length ? base.coins : base.row.top_coins} />
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Trade breakdown" description="Long/short split, largest trades, timing" />
            <div className="px-4 pb-4">
              <TradeBreakdown trips={base.recent_trips} accountValueUsd={base.row.account_value_usd} />
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
