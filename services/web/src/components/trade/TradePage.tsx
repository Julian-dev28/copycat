"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { EmptyAccountBanner } from "@/components/EmptyAccountBanner";
import { useNow } from "@/hooks/useNow";
import { useScoutTraders } from "@/hooks/useScout";
import { isValidAddress, normAddr } from "@/lib/address";
import type { EngineStatus, Settings } from "@/lib/api/types";
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
import { TradeDemoBanner, TradeGate } from "./TradeGate";
import { withDemo } from "./bits";

const BOARD_QUERY = boardStateToApiQuery({ ...DEFAULT_BOARD, limit: MAX_LIMIT });

export function TradePage() {
  const { demo } = useTradeMode();
  const { hasToken, unauthorized } = useAuth();
  if (!demo && (!hasToken || unauthorized)) return <TradeGate unauthorized={unauthorized} />;
  return <TradeInner />;
}

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

  function select(address: string, scrollTo?: "header" | "ticket") {
    const q = new URLSearchParams(sp.toString());
    q.set("w", normAddr(address));
    router.replace(`${pathname}?${q}`, { scroll: false });
    const target = scrollTo ?? (typeof window !== "undefined" && window.innerWidth < 768 ? "header" : null);
    if (target) setTimeout(() => document.getElementById(target === "ticket" ? "ticket" : "wallet-header")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  return (
    <div className="flex flex-col gap-4">
      {demo ? (
        <TradeDemoBanner
          acct={acct}
          hrefFor={(a) => {
            const q = new URLSearchParams(sp.toString());
            if (a === "default") q.delete("acct");
            else q.set("acct", a);
            return `${pathname}?${q}`;
          }}
        />
      ) : null}
      {!list.length && !wallets.isLoading ? <Explainer scoutHref={scoutHref} /> : null}
      <EmptyAccountBanner status={status.data as EngineStatus | undefined} settings={settings.data as Settings | undefined} />
      <div className="grid gap-4 md:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[19.5rem_minmax(0,1fr)_21rem]">
        <div className="md:row-span-2 xl:sticky xl:top-20 xl:row-span-1 xl:h-[calc(100vh-6.5rem)] xl:self-start">
          <MarketsPanel
            rows={rows}
            leaders={leaders}
            selected={selected}
            onSelect={(a) => select(a)}
            loading={traders.isLoading}
            error={traders.error ? problemText(traders.error, "Scout traders") : null}
            scoutHref={scoutHref}
          />
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
          />
        ) : (
          <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted xl:col-span-2">
            {traders.isLoading ? "Loading markets…" : "Pick a wallet on the left."}
          </div>
        )}
      </div>
      <YourWallets
        wallets={list}
        settings={settings.data}
        names={names}
        selected={selected}
        loading={wallets.isLoading}
        error={wallets.error ? problemText(wallets.error, "wallets") : null}
        onAdjust={(a) => select(a, "ticket")}
        nowMs={nowMs}
        sparks={Object.fromEntries(rows.map((r) => [normAddr(r.address), rowQuote(r).spark]))}
        empty={<p className="text-sm text-muted">Nothing invested yet. Pick a trader, set an amount, press Copy trader: it shows up here like an open position.</p>}
      />
    </div>
  );
}
