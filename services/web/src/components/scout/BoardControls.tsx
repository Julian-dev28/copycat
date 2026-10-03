"use client";

import { useState, type KeyboardEvent } from "react";
import { clsx } from "clsx";
import { LayoutGrid, Rows3, Search, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Switch } from "@/components/ui/Switch";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { useSyncedState } from "@/hooks/useSyncedState";
import { coinLabel, STYLE_META } from "@/lib/scout/labels";
import { countActiveFilters, parseAmount, SORT_OPTIONS, type BoardState } from "@/lib/scout/query";
import { PNL_WINDOWS, TRADING_STYLES, type ScoutPresets } from "@/lib/scout/types";
import { WINDOW_LABEL } from "@/lib/scout/window";

type Update = (patch: Partial<BoardState>) => void;

function Chip({ active, onClick, children, title }: { active: boolean; onClick: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      title={title}
      onClick={onClick}
      className={clsx(
        "inline-flex flex-shrink-0 items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active ? "border-accent bg-accent-soft text-accent" : "border-border bg-surface text-muted hover:border-foreground/30 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function PresetRow({ state, presets, update }: { state: BoardState; presets?: ScoutPresets; update: Update }) {
  return (
    <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="group" aria-label="Presets">
      <Chip active={state.preset === "all"} onClick={() => update({ preset: "all" })}>
        All traders
      </Chip>
      <Chip active={state.preset === "hip3"} onClick={() => update({ preset: "hip3" })} title="Half or more of top-coin volume on HIP-3 (xyz:) markets">
        HIP-3 equities{presets?.hip3 ? <span className="font-num opacity-70">{presets.hip3}</span> : null}
      </Chip>
      {presets?.coins.map((c) => (
        <Chip
          key={c.coin}
          active={state.preset === `coin:${c.coin}`}
          onClick={() => update({ preset: `coin:${c.coin}` })}
          title={`Traders whose #1 coin is ${c.coin}`}
        >
          Top {coinLabel(c.coin).name}
          {c.traders ? <span className="font-num opacity-70">{c.traders}</span> : null}
        </Chip>
      ))}
    </div>
  );
}

function SearchBox({ value, onCommit }: { value: string; onCommit: (q: string) => void }) {
  const [draft, setDraft] = useSyncedState(value);
  const commit = useDebouncedCallback((q: string) => onCommit(q.trim()), 300);
  return (
    <div className="relative min-w-0 flex-1 sm:max-w-xs">
      <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" aria-hidden="true" />
      <input
        type="search"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          commit(e.target.value);
        }}
        placeholder="Address or name"
        aria-label="Search by address prefix or name"
        className="w-full rounded-lg border border-border bg-surface-2 py-1.5 pr-3 pl-8 text-sm text-foreground placeholder:text-muted"
      />
    </div>
  );
}

export function Toolbar({
  state,
  update,
  filtersOpen,
  onToggleFilters,
}: {
  state: BoardState;
  update: Update;
  filtersOpen: boolean;
  onToggleFilters: () => void;
}) {
  const sortValue = `${state.sort}:${state.order}`;
  const known = SORT_OPTIONS.some((o) => `${o.sort}:${o.order}` === sortValue);
  const nFilters = countActiveFilters(state);
  return (
    <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-64">
          <SegmentedControl
            aria-label="PnL window"
            options={PNL_WINDOWS.map((w) => ({ value: w, label: WINDOW_LABEL[w] }))}
            value={state.window}
            onChange={(w) => update({ window: w })}
          />
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <span className="sr-only sm:not-sr-only">Sort</span>
          <select
            value={sortValue}
            onChange={(e) => {
              const [sort, order] = e.target.value.split(":");
              update({ sort: sort as BoardState["sort"], order: order as BoardState["order"] });
            }}
            className="rounded-lg border border-border bg-surface-2 px-2 py-1.5 text-sm text-foreground"
          >
            {!known ? <option value={sortValue}>Custom ({state.sort}, {state.order})</option> : null}
            {SORT_OPTIONS.map((o) => (
              <option key={`${o.sort}:${o.order}`} value={`${o.sort}:${o.order}`}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="PnL unit">
          {(["usd", "pct"] as const).map((u) => (
            <button
              key={u}
              type="button"
              role="radio"
              aria-checked={state.unit === u}
              onClick={() => update({ unit: u })}
              className={clsx(
                "font-num rounded-md px-2.5 py-1 text-xs font-semibold",
                state.unit === u ? "bg-accent text-accent-foreground" : "text-muted hover:text-foreground",
              )}
            >
              {u === "usd" ? "$" : "%"}
            </button>
          ))}
        </div>
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="View">
          {(
            [
              ["cards", LayoutGrid, "Cards"],
              ["table", Rows3, "Table"],
            ] as const
          ).map(([v, Icon, label]) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={state.view === v}
              aria-label={label}
              title={label}
              onClick={() => update({ view: v })}
              className={clsx("rounded-md px-2 py-1", state.view === v ? "bg-accent text-accent-foreground" : "text-muted hover:text-foreground")}
            >
              <Icon size={15} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <SearchBox value={state.q} onCommit={(q) => update({ q })} />
        <Button size="sm" variant={filtersOpen || nFilters ? "primary" : "secondary"} onClick={onToggleFilters} aria-expanded={filtersOpen}>
          <SlidersHorizontal size={13} aria-hidden="true" />
          Filters{nFilters ? ` (${nFilters})` : ""}
        </Button>
      </div>
    </div>
  );
}

/** Number field that commits on blur or Enter, so typing "10000" doesn't refetch five times. */
function NumberField({
  id,
  label,
  value,
  onCommit,
  leading,
  trailing,
  placeholder,
}: {
  id: string;
  label: string;
  value: number | null;
  onCommit: (v: number | null) => void;
  leading?: string;
  trailing?: string;
  placeholder?: string;
}) {
  const [draft, setDraft] = useSyncedState(value === null ? "" : String(value));
  function commit() {
    const n = parseAmount(draft);
    if (n === undefined) setDraft(value === null ? "" : String(value));
    else onCommit(n);
  }
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="text-[11px] text-muted">{label}</span>
      <Input
        id={id}
        inputMode="decimal"
        value={draft}
        placeholder={placeholder}
        leading={leading}
        trailing={trailing}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
          if (e.key === "Enter") commit();
        }}
        className="font-num"
      />
    </label>
  );
}

const ACTIVE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any time" },
  { value: "24", label: "Last 24h" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
];

export function FilterPanel({ state, update, onClear }: { state: BoardState; update: Update; onClear: () => void }) {
  const [coinDraft, setCoinDraft] = useState("");
  function addCoin() {
    const c = coinDraft.trim();
    if (!c) return;
    const norm = c.includes(":") ? c : c.toUpperCase();
    if (!state.coins.includes(norm)) update({ coins: [...state.coins, norm] });
    setCoinDraft("");
  }
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <NumberField id="f-min-av" label="Account value min" leading="$" placeholder="10k" value={state.minAv} onCommit={(v) => update({ minAv: v })} />
        <NumberField id="f-max-av" label="Account value max" leading="$" placeholder="any" value={state.maxAv} onCommit={(v) => update({ maxAv: v })} />
        <NumberField id="f-min-pnl" label={`PnL ${WINDOW_LABEL[state.window]} min`} leading="$" placeholder="any" value={state.minPnl} onCommit={(v) => update({ minPnl: v })} />
        <NumberField id="f-max-pnl" label={`PnL ${WINDOW_LABEL[state.window]} max`} leading="$" placeholder="any" value={state.maxPnl} onCommit={(v) => update({ maxPnl: v })} />
        <NumberField id="f-min-fit" label="Copy Fit min" placeholder="0" value={state.minFit || null} onCommit={(v) => update({ minFit: Math.min(state.maxFit, Math.max(0, Math.round(v ?? 0))) })} />
        <NumberField id="f-max-fit" label="Copy Fit max" placeholder="100" value={state.maxFit === 100 ? null : state.maxFit} onCommit={(v) => update({ maxFit: Math.max(state.minFit, Math.min(100, Math.round(v ?? 100))) })} />
        <NumberField id="f-max-dd" label="His max DD (30d) at most" trailing="%" placeholder="any" value={state.maxDd} onCommit={(v) => update({ maxDd: v === null ? null : Math.max(0, v) })} />
        <NumberField id="f-min-trips" label="Trips (30d) at least" placeholder="any" value={state.minTrips} onCommit={(v) => update({ minTrips: v === null ? null : Math.max(0, Math.round(v)) })} />
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] text-muted">Trading style</span>
        <div className="flex flex-wrap gap-1.5">
          {TRADING_STYLES.map((st) => {
            const on = state.styles.includes(st);
            return (
              <Chip key={st} active={on} title={STYLE_META[st].hint} onClick={() => update({ styles: on ? state.styles.filter((x) => x !== st) : [...state.styles, st] })}>
                {STYLE_META[st].label}
              </Chip>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-muted">Last active</span>
          <select
            value={state.activeWithinH === null ? "" : String(state.activeWithinH)}
            onChange={(e) => update({ activeWithinH: e.target.value ? Number(e.target.value) : null })}
            className="rounded-lg border border-border bg-surface-2 px-2 py-2 text-sm text-foreground"
          >
            {ACTIVE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-muted">Trades these coins</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {state.coins.map((c) => (
              <span key={c} className="font-num inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-1 text-xs text-accent">
                {c}
                <button type="button" aria-label={`Remove ${c}`} onClick={() => update({ coins: state.coins.filter((x) => x !== c) })}>
                  <X size={11} aria-hidden="true" />
                </button>
              </span>
            ))}
            <input
              value={coinDraft}
              onChange={(e) => setCoinDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addCoin();
              }}
              onBlur={addCoin}
              placeholder="BTC, xyz:TSLA…"
              aria-label="Add a coin filter"
              className="font-num w-32 rounded-lg border border-border bg-surface-2 px-2 py-1.5 text-sm text-foreground placeholder:text-muted"
            />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm" htmlFor="f-hide-flagged">
          <Switch id="f-hide-flagged" checked={state.hideFlagged} onChange={(v) => update({ hideFlagged: v })} label="Hide flagged traders" />
          <span>
            Hide flagged
            <span className="block text-[11px] text-muted">liquidated, algo, vault, inactive</span>
          </span>
        </label>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear} disabled={!countActiveFilters(state)}>
          Clear filters
        </Button>
      </div>
    </div>
  );
}
