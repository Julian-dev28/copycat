"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { clsx } from "clsx";
import { useAuth } from "@/context/AuthContext";
import { EmptyAccountBanner } from "@/components/EmptyAccountBanner";
import { Drawer, Panel, Skeleton } from "@/components/ui";
import { useNow } from "@/hooks/useNow";
import { useScoutTraders } from "@/hooks/useScout";
import { isValidAddress, normAddr } from "@/lib/address";
import type { EngineStatus, Settings } from "@/lib/api/types";
import { shortenAddress } from "@/lib/format";
import { LABELS } from "@/lib/labels";
import { boardStateToApiQuery, DEFAULT_BOARD, MAX_LIMIT } from "@/lib/scout/query";
import { problemText } from "@/lib/trade/apiState";
import { buildMarkets } from "@/lib/trade/markets";
import { rowQuote } from "@/lib/trade/equityIndex";
import { COMMON_COINS } from "@/lib/trade/coinFilter";
import { useTradeMode, useTradeSettings, useTradeStatus, useWallets } from "./hooks";
import { MarketsPanel } from "./MarketsPanel";
import { Workspace } from "./Workspace";
import { YourWallets } from "./YourWallets";
import { Explainer } from "./Explainer";
import { DemoAccountSwitch, TradeGate } from "./TradeGate";
import { CatAvatar } from "./CatAvatar";
import { withDemo } from "./bits";

const BOARD_QUERY = boardStateToApiQuery({ ...DEFAULT_BOARD, limit: MAX_LIMIT });

export function TradePage() {
  const { demo } = useTradeMode();
  const { hasToken, unauthorized } = useAuth();
  if (!demo && (!hasToken || unauthorized)) return <TradeGate unauthorized={unauthorized} />;
  return <TradeInner />;
}

/**
 * Trade (DESIGN 6): Markets 300px | trader detail | ticket 360px at 1280px+;
 * from 1024px the markets list folds into a 56px rail that opens a drawer;
 * under 1024px one column with the ticket as a bottom sheet. Your copies
 * docks under the grid.
 */
function TradeInner() {
  const { demo, acct } = useTradeMode();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const nowMs = useNow();
  const traders = useScoutTraders(BOARD_QUERY);
  const settings = useTradeSettings();
  const status = useTradeStatus();
  const wallets = useWallets();
  const [marketsOpen, setMarketsOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const rows = traders.data?.rows ?? [];
  const leaders = settings.data?.leaders ?? [];
  const wParam = sp.get("w");
  const fallback = leaders[0] ?? buildMarkets(rows, leaders, "top", "")[0]?.address ?? null;
  const selected = wParam && isValidAddress(wParam) ? normAddr(wParam) : fallback;
  const list = wallets.data ?? [];
  const allCoins = [...new Set([...rows.flatMap((r) => r.top_coins.map((c) => c.coin)), ...COMMON_COINS])];
  const names = Object.fromEntries(rows.map((r) => [normAddr(r.address), r.display_name ?? null]));
  const scoutHref = withDemo("/scout", demo);
  const settingsHref = withDemo("/settings", demo, acct);
  const narrow = () => typeof window !== "undefined" && window.innerWidth < 1024;

  function select(address: string, scrollTo?: "header" | "ticket") {
    const q = new URLSearchParams(sp.toString());
    q.set("w", normAddr(address));
    router.replace(`${pathname}?${q}`, { scroll: false });
    setMarketsOpen(false);
    if (scrollTo === "ticket" && narrow()) {
      // phones/tablets: the ticket is the bottom sheet; open it instead of scrolling
      setSheetOpen(true);
      return;
    }
    const target = scrollTo ?? (narrow() ? "header" : null);
    if (target) setTimeout(() => document.getElementById(target === "ticket" ? "ticket" : "wallet-header")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  const markets = (
    <MarketsPanel
      rows={rows}
      leaders={leaders}
      selected={selected}
      onSelect={(a) => select(a)}
      loading={traders.isLoading}
      error={traders.error ? problemText(traders.error, "Scout traders") : null}
      scoutHref={scoutHref}
    />
  );

  return (
    <div className="flex flex-col gap-4 max-lg:pb-36">
      {demo ? (
        <div className="flex justify-end">
          <DemoAccountSwitch
            acct={acct}
            hrefFor={(a) => {
              const q = new URLSearchParams(sp.toString());
              if (a === "default") q.delete("acct");
              else q.set("acct", a);
              return `${pathname}?${q}`;
            }}
          />
        </div>
      ) : null}
      {!list.length && !wallets.isLoading ? <Explainer scoutHref={scoutHref} /> : null}
      <EmptyAccountBanner status={status.data as EngineStatus | undefined} settings={settings.data as Settings | undefined} />
      <div className="grid gap-4 lg:grid-cols-[3.5rem_minmax(0,1fr)_21rem] xl:grid-cols-[18.75rem_minmax(0,1fr)_22.5rem]">
        {/* markets: full panel at 1280px+, a rail from 1024px, a stacked panel below */}
        <div className="lg:col-start-1 lg:row-start-1 lg:sticky lg:top-24 lg:self-start xl:h-[calc(100dvh-7.5rem)]">
          <div className="hidden flex-col items-center gap-2 lg:flex xl:hidden">
            <button
              type="button"
              onClick={() => setMarketsOpen(true)}
              aria-label="Open markets"
              title="Markets"
              className="grid h-11 w-11 place-items-center rounded-xl border border-border bg-surface text-fg-soft shadow-e1 transition-colors hover:border-border-strong hover:text-fg"
            >
              <Search size={16} aria-hidden="true" />
            </button>
            {leaders.slice(0, 8).map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => select(a)}
                aria-label={`Open ${names[a] ?? shortenAddress(a)}`}
                aria-current={a === selected ? "true" : undefined}
                title={names[a] ?? shortenAddress(a)}
                className={clsx(
                  "grid h-11 w-11 place-items-center rounded-xl border transition-colors",
                  a === selected ? "border-accent bg-surface-3" : "border-transparent hover:bg-surface-2",
                )}
              >
                <CatAvatar address={a} size={26} />
              </button>
            ))}
          </div>
          <div className="lg:hidden xl:block xl:h-full">{markets}</div>
        </div>
        {selected ? (
          <Workspace
            key={selected}
            address={selected}
            row={rows.find((r) => normAddr(r.address) === selected) ?? null}
            settings={settings.data}
            status={status.data}
            wallet={list.find((w) => w.address === selected) ?? null}
            inBook={leaders.includes(selected)}
            nowMs={nowMs}
            settingsHref={settingsHref}
            allCoins={allCoins}
            sheetOpen={sheetOpen}
            onSheet={setSheetOpen}
          />
        ) : traders.isLoading ? (
          <>
            <Panel className="flex flex-col gap-3 p-5 lg:col-start-2 lg:row-start-1" role="status" aria-label="Loading markets">
              <Skeleton className="h-10 w-56" />
              <Skeleton className="h-[240px] w-full" />
              <Skeleton className="h-24 w-full" />
            </Panel>
            <Panel className="hidden flex-col gap-3 p-4 lg:col-start-3 lg:row-start-1 lg:flex" aria-hidden="true">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-11 w-full" />
            </Panel>
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted lg:col-span-2 lg:col-start-2 lg:row-start-1">
            Pick a trader from Markets.
          </div>
        )}
      </div>
      <YourWallets
        wallets={list}
        settings={settings.data}
        names={names}
        selected={selected}
        loading={wallets.isLoading}
        error={wallets.error ? problemText(wallets.error, "copies") : null}
        onAdjust={(a) => select(a, "ticket")}
        nowMs={nowMs}
        sparks={Object.fromEntries(rows.map((r) => [normAddr(r.address), rowQuote(r).spark]))}
        empty={<p className="text-sm text-muted">Nothing invested yet. Pick a trader, set an amount, press {LABELS.copyTrader}: it shows up here like an open position.</p>}
      />
      <Drawer open={marketsOpen} onClose={() => setMarketsOpen(false)} title="Markets">
        {marketsOpen ? markets : null}
      </Drawer>
    </div>
  );
}
