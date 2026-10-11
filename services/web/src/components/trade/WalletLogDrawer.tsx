"use client";

import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Loader2, X } from "lucide-react";
import { useEventStream } from "@/hooks/useEventStream";
import type { EngineEvent } from "@/lib/api/types";
import { formatAgo, formatLeverage, formatUsd } from "@/lib/format";
import { problemText } from "@/lib/trade/apiState";
import { eventKind, eventLine, matchesFilter, mergeEvents, type EventFilter, type EventKind } from "@/lib/trade/walletEvents";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useTradeMode, useWalletEvents } from "./hooks";

const KIND_TONE: Record<EventKind, string> = {
  open: "bg-success/15 text-success",
  add: "bg-success/10 text-success",
  reduce: "bg-warning/15 text-warning",
  close: "bg-accent-soft text-accent",
  skip: "bg-surface-2 text-muted",
  other: "bg-surface-2 text-muted",
};

/** One wallet's log in a side drawer: opens, adds, reduces, closes and every skip with its reason. */
export function WalletLogDrawer({ open, onClose, address, name }: { open: boolean; onClose: () => void; address: string; name: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { demo } = useTradeMode();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      aria-label={`Log for ${name}`}
      className="fixed top-0 right-0 left-auto m-0 h-full max-h-none w-full max-w-md rounded-none border-l border-border bg-surface p-0 text-foreground backdrop:bg-black/60"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Log: {name}</h2>
            <p className="text-[11px] text-muted">Newest first. Every copy action and every skip, with its reason.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close the log" className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-foreground">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        {open ? demo ? <LogBody address={address} live={[]} liveState={null} /> : <LiveLogBody address={address} /> : null}
      </div>
    </dialog>
  );
}

/** Live api: the SSE feed is merged on top of the paged history (only while the drawer is open). */
function LiveLogBody({ address }: { address: string }) {
  const { events, state } = useEventStream();
  return <LogBody address={address} live={events} liveState={state} />;
}

function LogBody({ address, live, liveState }: { address: string; live: EngineEvent[]; liveState: string | null }) {
  const [filter, setFilter] = useState<EventFilter>("all");
  const q = useWalletEvents(address, true);
  const pages = (q.data?.pages ?? []).map((p) => p.events);
  const fallback = q.data?.pages.some((p) => p.fallback) ?? false;
  const all = mergeEvents(live, pages, address);
  const shown = all.filter((e) => matchesFilter(e, filter));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <SegmentedControl<EventFilter>
          aria-label="Which events"
          options={[{ value: "all", label: "All" }, { value: "trades", label: "Trades" }, { value: "skips", label: "Skips" }]}
          value={filter}
          onChange={setFilter}
        />
        {liveState === "open" ? <span className="whitespace-nowrap rounded-full bg-success/15 px-2 py-0.5 text-[10px] font-medium text-success">live</span> : null}
      </div>
      {fallback ? <p className="px-4 pt-2 text-[11px] text-warning">Your api has no per-wallet log yet: this is the shared event tail, filtered to this wallet.</p> : null}
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto" aria-live="polite" aria-label="Wallet events">
        {q.isLoading ? (
          <li className="flex items-center gap-2 px-4 py-6 text-sm text-muted"><Loader2 size={13} className="animate-spin" aria-hidden="true" /> Loading the log…</li>
        ) : q.error ? (
          <li className="px-4 py-6 text-sm text-danger">{problemText(q.error, "wallet log")}</li>
        ) : !shown.length ? (
          <li className="px-4 py-6 text-center text-sm text-muted">{filter === "all" ? "Nothing logged for this wallet yet." : "Nothing of that kind yet."}</li>
        ) : (
          shown.map((e, i) => <EventRow key={`${e.ts_ms}-${e.action}-${e.coin}-${i}`} e={e} />)
        )}
      </ul>
      {q.hasNextPage ? (
        <button type="button" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()} className="border-t border-border py-2 text-xs font-medium text-accent hover:underline disabled:opacity-50">
          {q.isFetchingNextPage ? "Loading…" : "Older events"}
        </button>
      ) : null}
    </div>
  );
}

function EventRow({ e }: { e: EngineEvent }) {
  const k = eventKind(e);
  return (
    <li className="flex flex-col gap-0.5 px-4 py-2 text-sm">
      <span className="flex items-start gap-2">
        <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", KIND_TONE[k])}>{e.action}</span>
        <span className={clsx("min-w-0 flex-1 break-words", k === "skip" && "text-muted")}>{eventLine(e)}</span>
        <span className="font-num text-[11px] whitespace-nowrap text-muted" title={new Date(e.ts_ms).toISOString()}>{formatAgo(e.ts_ms)}</span>
      </span>
      {k !== "skip" && (e.notional_usd || e.leverage || e.reason) ? (
        <span className="font-num pl-1 text-[11px] text-muted">
          {e.notional_usd ? formatUsd(e.notional_usd) : null}
          {e.leverage ? ` · ${formatLeverage(e.leverage)}` : null}
          {e.reason ? ` · ${e.reason}` : null}
          {e.dry_run ? " · dry run" : null}
        </span>
      ) : null}
    </li>
  );
}
