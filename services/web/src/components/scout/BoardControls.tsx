"use client";

import { useState, type KeyboardEvent, type ReactNode } from "react";
import { clsx } from "clsx";
import { Search, Settings2, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { Input } from "@/components/ui/Input";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Switch } from "@/components/ui/Switch";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { useSyncedState } from "@/hooks/useSyncedState";
import { HL_MIN_ORDER_USD, MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { coinLabel, STYLE_META } from "@/lib/scout/labels";
import { activeFilterChips, countActiveFilters, parseAmount, SORT_OPTIONS, type BoardState } from "@/lib/scout/query";
import { leverageChoiceOf, leverageN, leveragePatch, type LeverageChoice } from "@/lib/scout/simTerms";
import { PNL_WINDOWS, TRADING_STYLES, type ScoutPresets, type ScoutSimTerms } from "@/lib/scout/types";
import { WINDOW_LABEL } from "@/lib/scout/window";

type Update = (patch: Partial<BoardState>) => void;

const SELECT = "h-8 rounded-sm border border-border bg-surface-2 pr-7 pl-3 text-xs text-fg transition-colors hover:border-border-strong";

function Chip({ active, onClick, children, title }: { active: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      title={title}
      onClick={onClick}
      className={clsx(
        "inline-flex h-8 flex-shrink-0 items-center gap-1.5 rounded-sm border px-3 text-xs font-medium transition-colors duration-[var(--dur-fast)]",
        active ? "border-border-strong bg-surface-3 text-fg shadow-e1" : "border-border bg-surface text-muted hover:border-border-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

export function PresetRow({ state, presets, update }: { state: BoardState; presets?: ScoutPresets; update: Update }) {
  return (
    <div className="scroll-fade-x -mx-4 flex gap-1.5 px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0 sm:[mask-image:none]" role="group" aria-label="Presets">
      <Chip active={state.preset === "all"} onClick={() => update({ preset: "all" })}>
        All traders
      </Chip>
      <Chip
        active={state.preset === "copyable"}
        onClick={() => update({ preset: "copyable" })}
        title="The copy-sim opened at least 5 copies of this wallet at the current sim terms: it could actually follow them at that size. The rest nibble under the $10.50 minimum, trade too rarely, or sat idle."
      >
        Copyable{presets?.copyable ? <span className="num-sm text-muted">{presets.copyable}</span> : null}
      </Chip>
      <Chip active={state.preset === "hip3"} onClick={() => update({ preset: "hip3" })} title="Half or more of top-coin volume on HIP-3 (xyz:) markets">
        HIP-3 equities{presets?.hip3 ? <span className="num-sm text-muted">{presets.hip3}</span> : null}
      </Chip>
      {(presets?.custom ?? 0) > 0 || state.preset === "custom" ? (
        <Chip active={state.preset === "custom"} onClick={() => update({ preset: "custom" })} title="Wallets you added by hand, scored and simmed like every leaderboard wallet">
          Custom{presets?.custom ? <span className="num-sm text-muted">{presets.custom}</span> : null}
        </Chip>
      ) : null}
      {presets?.coins.map((c) => (
        <Chip key={c.coin} active={state.preset === `coin:${c.coin}`} onClick={() => update({ preset: `coin:${c.coin}` })} title={`Traders whose #1 coin is ${c.coin}`}>
          Top {coinLabel(c.coin).name}
          {c.traders ? <span className="num-sm text-muted">{c.traders}</span> : null}
        </Chip>
      ))}
    </div>
  );
}

function SearchBox({ value, onCommit }: { value: string; onCommit: (q: string) => void }) {
  const [draft, setDraft] = useSyncedState(value);
  const commit = useDebouncedCallback((q: string) => onCommit(q.trim()), 300);
  return (
    <div className="min-w-0 flex-1 sm:w-56 sm:flex-none">
      <Input
        type="search"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          commit(e.target.value);
        }}
        leading={<Search size={14} aria-hidden="true" />}
        placeholder="Address or name"
        aria-label="Search by address prefix or name"
      />
    </div>
  );
}

/**
 * The board's control bar: window, unit and view on the left, search, sort
 * and the Filters sheet on the right. Active filters show as removable chips
 * under it, so the sheet never hides what is applied.
 */
export function Toolbar({
  state,
  update,
  onOpenFilters,
  onClearFilters,
  addWallet,
  simTerms,
}: {
  state: BoardState;
  update: Update;
  onOpenFilters: () => void;
  onClearFilters: () => void;
  /** The "Add wallet" box (components/scout/custom.tsx), rendered with the search and sort controls. */
  addWallet?: ReactNode;
  /** The "Sim terms" button + drawer (below), rendered next to Filters. */
  simTerms?: ReactNode;
}) {
  const sortValue = `${state.sort}:${state.order}`;
  const known = SORT_OPTIONS.some((o) => `${o.sort}:${o.order}` === sortValue);
  const nFilters = countActiveFilters(state);
  const chips = activeFilterChips(state, (st) => STYLE_META[st].label);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl
            className="sm:w-64"
            aria-label="PnL window"
            options={PNL_WINDOWS.map((w) => ({ value: w, label: WINDOW_LABEL[w] }))}
            value={state.window}
            onChange={(w) => update({ window: w })}
          />
          <SegmentedControl
            className="w-auto flex-1 sm:w-40 sm:flex-none"
            aria-label="Show PnL as"
            options={[
              { value: "usd", label: "$ PnL" },
              { value: "pct", label: "% ROI" },
            ]}
            value={state.unit}
            onChange={(u) => update({ unit: u })}
          />
          <SegmentedControl
            className="w-auto flex-1 sm:w-40 sm:flex-none"
            aria-label="View"
            options={[
              { value: "cards", label: "Cards" },
              { value: "table", label: "Table" },
            ]}
            value={state.view}
            onChange={(v) => update({ view: v })}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {addWallet}
          <SearchBox value={state.q} onCommit={(q) => update({ q })} />
          <label className="flex-shrink-0">
            <span className="sr-only">Sort</span>
            <select
              value={sortValue}
              onChange={(e) => {
                const [sort, order] = e.target.value.split(":");
                update({ sort: sort as BoardState["sort"], order: order as BoardState["order"] });
              }}
              className={clsx(SELECT, "max-w-[9.5rem] sm:max-w-none")}
            >
              {!known ? (
                <option value={sortValue}>
                  Custom ({state.sort}, {state.order})
                </option>
              ) : null}
              {SORT_OPTIONS.map((o) => (
                <option key={`${o.sort}:${o.order}`} value={`${o.sort}:${o.order}`}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <Button size="sm" variant="secondary" onClick={onOpenFilters} aria-haspopup="dialog" className="flex-shrink-0">
            <SlidersHorizontal size={13} aria-hidden="true" />
            Filters
            {nFilters ? <span className="num-sm grid h-4 min-w-4 place-items-center rounded-sm bg-fg px-1 text-[10px] text-bg">{nFilters}</span> : null}
          </Button>
          {simTerms}
        </div>
      </div>
      {chips.length ? (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Active filters">
          {chips.map((c) => (
            <span key={c.key} className="inline-flex h-7 items-center gap-1 rounded-sm border border-border bg-surface-2 pr-1 pl-2.5 text-xs text-fg-soft">
              {c.label}
              <button
                type="button"
                aria-label={`Remove filter: ${c.label}`}
                onClick={() => update(c.clear)}
                className="grid h-5 w-5 place-items-center rounded-sm text-muted transition-colors hover:bg-surface-3 hover:text-fg"
              >
                <X size={11} aria-hidden="true" />
              </button>
            </span>
          ))}
          <button type="button" onClick={onClearFilters} className="px-2 text-xs font-medium text-muted transition-colors hover:text-fg">
            Clear all
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * "Sim terms" (contract v16): the equity/allocation/leverage/margin every
 * wallet on the board is simmed at, changeable on the fly. A button + drawer
 * next to Filters, so the terms are one click away without crowding the row.
 */
export function SimTermsButton({
  terms,
  onApply,
  applying,
  error,
}: {
  terms?: ScoutSimTerms;
  onApply: (terms: ScoutSimTerms) => void;
  applying?: boolean;
  error?: string | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)} aria-haspopup="dialog" className="flex-shrink-0" disabled={!terms}>
        <Settings2 size={13} aria-hidden="true" />
        Sim terms
      </Button>
      {terms ? (
        <SimTermsDrawer
          open={open}
          onClose={() => setOpen(false)}
          terms={terms}
          applying={applying}
          error={error}
          onApply={(t) => {
            onApply(t);
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function SimTermsDrawer({
  open,
  onClose,
  terms,
  onApply,
  applying,
  error,
}: {
  open: boolean;
  onClose: () => void;
  terms: ScoutSimTerms;
  onApply: (terms: ScoutSimTerms) => void;
  applying?: boolean;
  error?: string | null;
}) {
  const [draft, setDraft] = useSyncedState(terms);
  const choice = leverageChoiceOf(draft);
  const lev = leverageN(draft);
  const patch = (p: Partial<ScoutSimTerms>) => setDraft({ ...draft, ...p });
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Sim terms"
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button size="sm" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={() => onApply(draft)} disabled={applying}>
            {applying ? "Applying…" : "Apply"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <label htmlFor="st-live" className="flex items-center justify-between gap-3 text-sm">
          <span>
            Use my live trading settings
            <span className="block text-xs text-muted">Sim every wallet at your own Settings tab and sim equity, the pre-v16 board.</span>
          </span>
          <Switch id="st-live" checked={draft.use_live_settings} onChange={(v) => patch({ use_live_settings: v })} label="Use my live trading settings" />
        </label>
        <Group title="Equity and allocation">
          <div className="grid grid-cols-2 gap-3">
            <NumberField
              id="st-equity"
              label="Account equity"
              leading="$"
              value={draft.sim_equity_usd}
              onCommit={(v) => patch({ sim_equity_usd: Math.max(1, v ?? draft.sim_equity_usd) })}
            />
            <NumberField
              id="st-alloc"
              label="Per wallet"
              leading="$"
              value={draft.allocation_usd}
              onCommit={(v) => patch({ allocation_usd: Math.max(HL_MIN_ORDER_USD, v ?? draft.allocation_usd) })}
            />
          </div>
        </Group>
        <Group title="Leverage">
          <SegmentedControl<LeverageChoice>
            aria-label="Leverage mode"
            options={[
              { value: "their", label: "Their leverage" },
              { value: "fixed", label: "Fixed" },
            ]}
            value={choice}
            onChange={(c) => patch(leveragePatch(c, lev))}
            disabled={draft.use_live_settings}
          />
          <NumberField
            id="st-lev"
            label={choice === "fixed" ? "Leverage" : "Leverage cap"}
            trailing="x"
            value={lev}
            onCommit={(v) => patch(leveragePatch(choice, Math.max(1, Math.min(MAX_LEVERAGE_CAP, Math.round(v ?? lev)))))}
          />
        </Group>
        <Group title="Margin">
          <SegmentedControl
            aria-label="Margin mode"
            options={[
              { value: "isolated", label: "Isolated" },
              { value: "cross", label: "Cross" },
            ]}
            value={draft.margin_mode}
            onChange={(m) => patch({ margin_mode: m })}
            disabled={draft.use_live_settings}
          />
        </Group>
        {error ? <p className="text-xs text-danger">{error}</p> : null}
      </div>
    </Drawer>
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
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1.5">
      <span className="text-label text-muted">{label}</span>
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

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-3 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <legend className="mb-3 text-heading text-fg">{title}</legend>
      {children}
    </fieldset>
  );
}

const ACTIVE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any time" },
  { value: "24", label: "Last 24h" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
];

/** All filters in one sheet (right drawer on desktop, bottom sheet on phones). Every change applies at once. */
export function FilterSheet({
  open,
  onClose,
  state,
  update,
  onClear,
  resultCount,
}: {
  open: boolean;
  onClose: () => void;
  state: BoardState;
  update: Update;
  onClear: () => void;
  resultCount?: number;
}) {
  const [coinDraft, setCoinDraft] = useState("");
  const n = countActiveFilters(state);
  function addCoin() {
    const c = coinDraft.trim();
    if (!c) return;
    const norm = c.includes(":") ? c : c.toUpperCase();
    if (!state.coins.includes(norm)) update({ coins: [...state.coins, norm] });
    setCoinDraft("");
  }
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Filters"
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button size="sm" variant="ghost" onClick={onClear} disabled={!n}>
            Clear filters
          </Button>
          <Button size="sm" variant="primary" onClick={onClose}>
            {resultCount === undefined ? "Done" : `Show ${resultCount} trader${resultCount === 1 ? "" : "s"}`}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <Group title="Size and results">
          <div className="grid grid-cols-2 gap-3">
            <NumberField id="f-min-av" label="Account min" leading="$" placeholder="e.g. 10k" value={state.minAv} onCommit={(v) => update({ minAv: v })} />
            <NumberField id="f-max-av" label="Account max" leading="$" placeholder="any" value={state.maxAv} onCommit={(v) => update({ maxAv: v })} />
            <NumberField id="f-min-pnl" label={`PnL ${WINDOW_LABEL[state.window]} min`} leading="$" placeholder="any" value={state.minPnl} onCommit={(v) => update({ minPnl: v })} />
            <NumberField id="f-max-pnl" label={`PnL ${WINDOW_LABEL[state.window]} max`} leading="$" placeholder="any" value={state.maxPnl} onCommit={(v) => update({ maxPnl: v })} />
          </div>
        </Group>
        <Group title="Quality">
          <div className="grid grid-cols-2 gap-3">
            <NumberField id="f-min-fit" label="Copy Fit min" placeholder="0" value={state.minFit || null} onCommit={(v) => update({ minFit: Math.min(state.maxFit, Math.max(0, Math.round(v ?? 0))) })} />
            <NumberField id="f-max-fit" label="Copy Fit max" placeholder="100" value={state.maxFit === 100 ? null : state.maxFit} onCommit={(v) => update({ maxFit: Math.max(state.minFit, Math.min(100, Math.round(v ?? 100))) })} />
            <NumberField id="f-max-dd" label="Their max DD 30d, at most" trailing="%" placeholder="any" value={state.maxDd} onCommit={(v) => update({ maxDd: v === null ? null : Math.max(0, v) })} />
            <NumberField id="f-min-trips" label="Trips 30d, at least" placeholder="any" value={state.minTrips} onCommit={(v) => update({ minTrips: v === null ? null : Math.max(0, Math.round(v)) })} />
          </div>
          <label htmlFor="f-hide-flagged" className="flex items-center justify-between gap-3 text-sm">
            <span>
              Hide flagged traders
              <span className="block text-xs text-muted">liquidated in the sim, algo, vault, inactive</span>
            </span>
            <Switch id="f-hide-flagged" checked={state.hideFlagged} onChange={(v) => update({ hideFlagged: v })} label="Hide flagged traders" />
          </label>
        </Group>
        <Group title="How they trade">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Trading style">
            {TRADING_STYLES.map((st) => {
              const on = state.styles.includes(st);
              return (
                <Chip key={st} active={on} title={STYLE_META[st].hint} onClick={() => update({ styles: on ? state.styles.filter((x) => x !== st) : [...state.styles, st] })}>
                  {STYLE_META[st].label}
                </Chip>
              );
            })}
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-label text-muted">Last active</span>
            <select
              value={state.activeWithinH === null ? "" : String(state.activeWithinH)}
              onChange={(e) => update({ activeWithinH: e.target.value ? Number(e.target.value) : null })}
              className={clsx(SELECT, "h-10 w-full rounded-lg text-sm")}
            >
              {ACTIVE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="f-coin" className="text-label text-muted">
              Trades these coins
            </label>
            <div className="flex flex-wrap items-center gap-1.5">
              {state.coins.map((c) => (
                <span key={c} className="font-num inline-flex h-7 items-center gap-1 rounded-sm border border-border bg-surface-2 pr-1 pl-2.5 text-xs text-fg">
                  {c}
                  <button
                    type="button"
                    aria-label={`Remove ${c}`}
                    onClick={() => update({ coins: state.coins.filter((x) => x !== c) })}
                    className="grid h-5 w-5 place-items-center rounded-sm text-muted hover:bg-surface-3 hover:text-fg"
                  >
                    <X size={11} aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
            <Input
              id="f-coin"
              value={coinDraft}
              onChange={(e) => setCoinDraft(e.target.value)}
              onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCoin();
                }
              }}
              onBlur={addCoin}
              placeholder="BTC, xyz:TSLA… then Enter"
              className="font-num"
            />
          </div>
        </Group>
      </div>
    </Drawer>
  );
}
