"use client";

import { Suspense, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { clsx } from "clsx";
import { Telescope } from "lucide-react";
import { RequireToken } from "@/components/RequireToken";
import { LoadError, PageSkeleton } from "@/components/PageStates";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { FilterSheet, PresetRow, SimTermsButton, Toolbar } from "@/components/scout/BoardControls";
import { BoardTicker } from "@/components/scout/BoardTicker";
import { AddWalletBox } from "@/components/scout/custom";
import { TraderCard } from "@/components/scout/TraderCard";
import { TraderTable } from "@/components/scout/TraderTable";
import { ApiTooOld, DeparturesNote, RefreshBadge, scoutHref } from "@/components/scout/bits";
import { toast } from "@/components/ui/Toast";
import { useNow } from "@/hooks/useNow";
import {
  useAddCustomWallet, useRemoveCustomWallet, useScoutBook, useScoutMode, useScoutPresets, useScoutRefresh,
  useScoutSimTerms, useScoutStatus, useScoutTraders, useSetScoutSimTerms,
} from "@/hooks/useScout";
import { addedText } from "@/lib/scout/addWallet";
import { isApiTooOld } from "@/lib/scout/api";
import {
  boardStateToApiQuery, boardStateToSearch, clearFilters, countActiveFilters, DEFAULT_BOARD, MAX_LIMIT, PAGE_SIZE, parseBoardState,
  type BoardState,
} from "@/lib/scout/query";
import { reRankingNote, simTermsNote } from "@/lib/scout/simTerms";

export default function ScoutPage() {
  return (
    <Suspense fallback={<PageSkeleton label="Loading Scout" />}>
      <ScoutGate />
    </Suspense>
  );
}

/** Demo mode needs no token; live mode goes through the usual token gate. */
function ScoutGate() {
  const { demo } = useScoutMode();
  return demo ? <ScoutBoard /> : (
    <RequireToken>
      <ScoutBoard />
    </RequireToken>
  );
}

function ScoutBoard() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { demo } = useScoutMode();
  const state = parseBoardState(new URLSearchParams(sp.toString()));
  const apiQuery = boardStateToApiQuery(state);
  const traders = useScoutTraders(apiQuery);
  const presets = useScoutPresets();
  const book = useScoutBook();
  const refresh = useScoutRefresh();
  const addCustom = useAddCustomWallet();
  const removeCustom = useRemoveCustomWallet();
  const simTerms = useScoutSimTerms();
  const setSimTerms = useSetScoutSimTerms();
  const status = useScoutStatus();
  const nowMs = useNow();
  const [filtersOpen, setFiltersOpen] = useState(false);

  /** Add any wallet to the board, then open its file (it builds on demand, the row follows). */
  function addWallet(address: string) {
    addCustom.mutate(address, {
      onSuccess: (res) => {
        toast(addedText(address, res.queued), { tone: "success" });
        router.push(scoutHref(`/scout/${address}`, demo));
      },
      onError: (e) => toast.error(e.message),
    });
  }

  function removeWallet(address: string) {
    removeCustom.mutate(address, {
      onSuccess: () => toast("Removed from Scout"),
      onError: (e) => toast.error(e.message),
    });
  }
  const removingCustom = removeCustom.isPending ? (removeCustom.variables ?? null) : null;

  function navigate(next: BoardState) {
    const qs = boardStateToSearch(next, demo ? { demo: "1" } : undefined);
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  /** Any change other than "show more" starts the list from the top again. */
  function update(patch: Partial<BoardState>) {
    navigate({ ...state, limit: "limit" in patch ? state.limit : DEFAULT_BOARD.limit, ...patch });
  }

  const page = traders.data;
  const tooOld = traders.isError && isApiTooOld(traders.error);
  const nFilters = countActiveFilters(state);

  let body: ReactNode;
  if (tooOld) body = <ApiTooOld what="the trader board" />;
  else if (traders.isError && !page) body = <LoadError what="the trader board" error={traders.error} onRetry={() => traders.refetch()} />;
  else if (!page) body = <BoardSkeleton />;
  else if (page.total === 0 && nFilters === 0 && state.preset === "all" && page.cohort_size === 0) {
    body = (
      <Panel className="flex flex-col items-center gap-3 px-5 py-12 text-center">
        <Telescope size={30} className="text-accent" aria-hidden="true" />
        <p className="text-sm font-semibold">No traders ranked yet</p>
        <p className="max-w-md text-sm text-muted">
          Scout ranks the Hyperliquid leaderboard by what copying each trader would have earned you. The first refresh reads about 300
          wallets and takes 40 to 60 minutes; after that it stays current on its own.
        </p>
        <Button variant="primary" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          Start the first refresh
        </Button>
        {refresh.isError ? <p className="text-xs text-danger">{refresh.error.message}</p> : null}
      </Panel>
    );
  } else if (page.rows.length === 0) {
    body = (
      <Panel className="flex flex-col items-center gap-2 px-5 py-10 text-center">
        <p className="text-sm font-semibold">No trader matches these filters</p>
        <p className="text-sm text-muted">{page.cohort_size} traders are ranked; loosen a filter or switch preset.</p>
        <Button size="sm" onClick={() => navigate({ ...clearFilters(state), preset: "all" })}>
          Clear filters and preset
        </Button>
      </Panel>
    );
  } else {
    const fetching = traders.isFetching && traders.isPlaceholderData;
    const cards = (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {page.rows.map((row, i) => (
          <TraderCard
            key={row.address}
            row={row}
            rank={i + 1}
            window={state.window}
            unit={state.unit}
            book={book}
            demo={demo}
            nowMs={nowMs}
            onRemoveCustom={removeWallet}
            removingCustom={removingCustom}
          />
        ))}
      </div>
    );
    body = (
      <div className={clsx("flex flex-col gap-4 transition-opacity", fetching && "opacity-60")} aria-busy={fetching}>
        {state.view === "table" ? (
          <>
            <div className="hidden sm:block">
              <TraderTable
                rows={page.rows}
                window={state.window}
                sort={state.sort}
                order={state.order}
                onSort={(sort, order) => update({ sort, order })}
                book={book}
                demo={demo}
                nowMs={nowMs}
                onRemoveCustom={removeWallet}
                removingCustom={removingCustom}
              />
            </div>
            <div className="sm:hidden">{cards}</div>
          </>
        ) : (
          cards
        )}
        <div className="flex flex-col items-center gap-2 text-xs text-muted">
          <span>
            Showing {page.rows.length} of {page.total}
            {page.total !== page.cohort_size ? ` (${page.cohort_size} ranked in all)` : ""}
          </span>
          {page.rows.length < page.total && state.limit < MAX_LIMIT ? (
            <Button size="sm" onClick={() => update({ limit: Math.min(MAX_LIMIT, state.limit + PAGE_SIZE) })}>
              Show {Math.min(PAGE_SIZE, page.total - page.rows.length)} more
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Scout</h1>
          <p className="text-sm text-muted">{simTerms.data ? simTermsNote(simTerms.data) : "Traders ranked by what copying them would have earned you."}</p>
        </div>
        {!tooOld ? <RefreshBadge cohort={page?.cohort_size} asOfMs={page?.as_of_ms} nowMs={nowMs} /> : null}
      </div>

      <BoardTicker rows={page?.rows ?? []} window={state.window} unit={state.unit} demo={demo} />

      {page?.stale_settings ? (
        <Notice tone="info" title="Re-ranking for your new terms">
          {status.data?.stage === "sim" ? reRankingNote(status.data.done, status.data.total) : "Your sim terms changed, so the copy sim is re-running. Until it finishes, Copy Fit and scores below are from the previous terms."}
        </Notice>
      ) : null}

      {setSimTerms.isError ? (
        <Notice tone="danger" title="Couldn't apply those sim terms">
          {setSimTerms.error.message}
        </Notice>
      ) : null}

      {book.addError ? (
        <Notice tone="danger" title="Couldn't add that trader to your copies">
          {book.addError.message}
        </Notice>
      ) : null}

      {presets.data ? <DeparturesNote departed={presets.data.departed} departedLiquidated={presets.data.departedLiquidated} /> : null}
      <PresetRow state={state} presets={presets.data} update={update} />
      <Toolbar
        state={state}
        update={update}
        onOpenFilters={() => setFiltersOpen(true)}
        onClearFilters={() => navigate(clearFilters(state))}
        addWallet={<AddWalletBox onAdd={addWallet} pending={addCustom.isPending} error={addCustom.error?.message} />}
        simTerms={
          <SimTermsButton
            terms={simTerms.data}
            applying={setSimTerms.isPending}
            error={setSimTerms.error?.message}
            onApply={(t) => setSimTerms.mutate(t)}
          />
        }
      />
      <FilterSheet
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        state={state}
        update={update}
        onClear={() => navigate(clearFilters(state))}
        resultCount={page?.total}
      />

      {body}
    </div>
  );
}

function BoardSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading traders">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="h-80 animate-pulse rounded-xl border border-border bg-surface" />
      ))}
    </div>
  );
}
