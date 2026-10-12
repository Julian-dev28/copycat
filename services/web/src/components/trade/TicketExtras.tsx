"use client";

import { clsx } from "clsx";
import { AlertTriangle, ArrowDownUp, Copy as CopyIcon } from "lucide-react";
import { DIRECTION_META } from "@/lib/trade/direction";
import type { TradeDirection } from "@/lib/trade/types";
import { CoinChips } from "./CoinChips";
import { Inherit } from "./Inherit";

/** The big Copy | Counter switch at the top of the ticket, with its one-line explanation. */
export function DirectionSwitch({
  value,
  onChange,
  set,
  onReset,
  supported,
  globalSource,
}: {
  value: TradeDirection;
  onChange: (d: TradeDirection) => void;
  /** This wallet overrides the Settings direction. */
  set: boolean;
  onReset: () => void;
  supported: boolean;
  /** The ticket is on "Use global": picking a side moves it to custom. */
  globalSource: boolean;
}) {
  const opts: { v: TradeDirection; icon: typeof CopyIcon }[] = [
    { v: "copy", icon: CopyIcon },
    { v: "counter", icon: ArrowDownUp },
  ];
  return (
    <div className="flex flex-col gap-1.5">
      <span className="flex items-center justify-between text-sm font-medium">
        Direction
        {!globalSource && supported ? <Inherit set={set} onReset={onReset} label="direction" /> : null}
      </span>
      <div role="radiogroup" aria-label="Copy or counter this trader" className="grid grid-cols-2 gap-1 rounded-full border border-border bg-surface-2 p-1">
        {opts.map(({ v, icon: Icon }) => {
          const on = v === value;
          return (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={!supported}
              onClick={() => onChange(v)}
              className={clsx(
                "flex items-center justify-center gap-1.5 rounded-full py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-[var(--dur-base)] ease-in-out disabled:cursor-not-allowed disabled:opacity-50",
                // Not accent-filled (DESIGN 5 Segmented): the accent belongs to the primary action.
                on ? "bg-surface text-fg shadow-e1 dark:bg-surface-3" : "text-muted hover:text-fg",
              )}
            >
              <Icon size={14} aria-hidden="true" /> {DIRECTION_META[v].label}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted">{DIRECTION_META[value].line}</p>
      {!supported ? <p className="text-[11px] text-warn">Your api predates counter-trading (contract v8): traders are copied as-is.</p> : null}
      {supported && globalSource ? <p className="text-[11px] text-muted">Picking a side gives this trader its own terms.</p> : null}
    </div>
  );
}

/** "Only these coins" / "Never these coins" for one wallet; null lists follow Settings. */
export function CoinFilterFields({
  allow,
  block,
  allowSet,
  blockSet,
  hisCoins,
  allCoins,
  onAllow,
  onBlock,
  onReset,
  supported,
}: {
  allow: string[];
  block: string[];
  allowSet: boolean;
  blockSet: boolean;
  hisCoins: string[];
  allCoins: string[];
  onAllow: (l: string[]) => void;
  onBlock: (l: string[]) => void;
  onReset: (f: "allow" | "block") => void;
  supported: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="flex items-center justify-between text-sm font-medium">
          Only these coins
          <Inherit set={allowSet} onReset={() => onReset("allow")} label="only these coins" />
        </span>
        <CoinChips label="Only these coins" value={allow} onChange={onAllow} hisCoins={hisCoins} allCoins={allCoins} placeholder="Any coin (type to limit)" disabled={!supported} />
      </div>
      <div className="flex flex-col gap-1">
        <span className="flex items-center justify-between text-sm font-medium">
          Never these coins
          <Inherit set={blockSet} onReset={() => onReset("block")} label="never these coins" />
        </span>
        <CoinChips label="Never these coins" value={block} onChange={onBlock} hisCoins={hisCoins} allCoins={allCoins} placeholder="None" tone="danger" disabled={!supported} />
      </div>
      <p className="text-[11px] text-muted">Filters stop new copies and adds only. Exits are always followed.</p>
      {!supported ? <p className="text-[11px] text-warn">Your api predates coin filters (contract v8).</p> : null}
    </div>
  );
}

export function AlgoWarning({ text }: { text: string }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft p-3 text-xs">
      <AlertTriangle size={14} className="mt-0.5 flex-shrink-0 text-warn" aria-hidden="true" />
      <p>
        <b className="block text-fg">Fast trader</b>
        <span className="text-muted">{text}</span>
      </p>
    </div>
  );
}
