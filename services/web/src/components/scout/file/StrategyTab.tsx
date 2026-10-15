"use client";

import { Loader2 } from "lucide-react";
import { LoadError } from "@/components/PageStates";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { ApiTooOld } from "@/components/scout/bits";
import { isApiTooOld } from "@/lib/scout/api";
import { hasClaudeThesis, isStale, keyNumbers, orderTheses } from "@/lib/scout/file/strategy";
import { EvidenceTable } from "./EvidenceTable";
import { useFingerprint, useTheses } from "./hooks";
import { StrategyHeatmap } from "./StrategyHeatmap";
import { ThesisCard, ThesisHint } from "./ThesisCard";

export function StrategyTab({ address }: { address: string }) {
  const fp = useFingerprint(address, true);
  const theses = useTheses(address, true);

  if (fp.isError && isApiTooOld(fp.error)) return <ApiTooOld what="the Strategy tab" />;
  if (fp.isError) return <LoadError what="the strategy fingerprint" error={fp.error} onRetry={() => fp.refetch()} />;
  if (!fp.data || fp.data.kind === "building") {
    const s = fp.data?.kind === "building" ? fp.data.status : null;
    return (
      <Panel className="flex items-center gap-3 p-5 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin text-accent" aria-hidden="true" />
        {s ? `Reading their fills and candles to build the fingerprint${s.total ? ` (${s.done}/${s.total})` : ""}. This page checks back every few seconds.` : "Loading strategy…"}
      </Panel>
    );
  }
  const f = fp.data.fingerprint;
  const list = orderTheses(theses.data ?? []);

  return (
    <div className="flex flex-col gap-4">
      <Panel className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap gap-1.5">
          {f.tags.map((t) => (
            <span key={t} className="rounded-sm border border-accent/30 bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
              {t}
            </span>
          ))}
        </div>
        <p className="text-sm leading-relaxed">{f.summary}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
          {keyNumbers(f).map((k) => (
            <div key={k.label} className="min-w-0">
              <dt className="text-[11px] text-muted">{k.label}</dt>
              <dd className="font-num text-sm font-semibold">{k.value}</dd>
              {k.hint ? <dd className="truncate text-[11px] text-muted">{k.hint}</dd> : null}
            </div>
          ))}
        </dl>
        <p className="text-[11px] text-muted">
          Fingerprint from {f.trips_analyzed} round trips over {f.window_days} days, computed {new Date(f.as_of_ms).toLocaleString("en-US", { hour12: false })}. Rules and
          candles only, no AI.
        </p>
      </Panel>

      <Panel>
        <PanelHeader title="When they enter" description="Trip entries by UTC hour and weekday" />
        <div className="px-4 pb-4">
          <StrategyHeatmap fp={f} />
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Evidence" description="The trades behind the claims above" />
        <div className="px-4 pb-4">
          <EvidenceTable examples={f.examples} />
        </div>
      </Panel>

      {f.caveats.length ? (
        <Panel className="p-4">
          <h3 className="text-sm font-semibold">Caveats</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
            {f.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <section className="flex flex-col gap-3" aria-label="Theses">
        <h2 className="text-sm font-semibold">Theses</h2>
        {theses.isError ? <LoadError what="the theses" error={theses.error} onRetry={() => theses.refetch()} /> : null}
        {list.map((t) => (
          <ThesisCard key={t.source} thesis={t} stale={isStale(t, f)} />
        ))}
        {theses.data && !list.length ? <p className="text-sm text-muted">No thesis yet.</p> : null}
        {theses.data && !hasClaudeThesis(list) ? <ThesisHint address={address} /> : null}
      </section>
    </div>
  );
}
