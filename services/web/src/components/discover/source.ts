/**
 * Where /discover reads runs and starts them. Live: the api. Demo (`?demo=1`):
 * a canned run built from the Scout demo board, kept in memory, so a demo
 * "Start" or "Copy" never reaches the api (UX audit #1).
 */
import { api, ApiError } from "@/lib/api/client";
import type { DiscoveryRun, Settings, StartDiscoveryRunBody } from "@/lib/api/types";
import { demoNowMs } from "@/lib/scout/api";
import { FIXTURE_COHORT, fixtureRows, fixtureSettings } from "@/lib/scout/fixtures";

export interface DiscoverySource {
  readonly demo: boolean;
  latest(): Promise<DiscoveryRun>;
  run(runId: string): Promise<DiscoveryRun>;
  start(body: StartDiscoveryRunBody): Promise<{ run_id: string }>;
}

export const liveDiscovery: DiscoverySource = {
  demo: false,
  latest: () => api.getLatestDiscoveryRun(),
  run: (id) => api.getDiscoveryRun(id),
  start: (body) => api.startDiscoveryRun(body),
};

/** How long a demo run "runs" before its results land. */
export const DEMO_RUN_MS = 2_500;

/** A finished run over the Scout demo board: top `topN` by score, at `simEquityUsd`. */
export function cannedRun(runId: string, startedMs: number, simEquityUsd: number, topN: number, settings?: Settings): DiscoveryRun {
  const nowMs = demoNowMs();
  const results = fixtureRows(nowMs)
    .map((r) => r.score)
    .sort((a, b) => b.score - a.score || a.address.localeCompare(b.address))
    .slice(0, Math.max(1, topN));
  return {
    run_id: runId, started_ms: startedMs, finished_ms: startedMs + DEMO_RUN_MS, status: "done",
    sim_equity_usd: simEquityUsd, sim_settings: settings ?? fixtureSettings(nowMs), candidates: FIXTURE_COHORT,
    scored: results.length, error: null, results,
  };
}

/** In-memory demo runs. `clock` is injectable for tests. */
export function demoDiscovery(clock: () => number = Date.now): DiscoverySource {
  const runs = new Map<string, { run: DiscoveryRun; readyMs: number }>();
  let latestId: string | null = "demo-0";
  runs.set("demo-0", { run: cannedRun("demo-0", clock() - 3_600_000, 1_000, 25), readyMs: 0 });
  let n = 0;
  const view = (id: string): DiscoveryRun => {
    const r = runs.get(id);
    if (!r) throw new ApiError(404, "no such run");
    if (clock() < r.readyMs) return { ...r.run, status: "running", finished_ms: null, scored: 0, results: [] };
    return r.run;
  };
  return {
    demo: true,
    latest: async () => {
      if (!latestId) throw new ApiError(404, "no runs yet");
      return view(latestId);
    },
    run: async (id) => view(id),
    start: async (body) => {
      const id = `demo-${++n}`;
      const now = clock();
      runs.set(id, { run: cannedRun(id, now, body.sim_equity_usd, body.top_n, body.settings), readyMs: now + DEMO_RUN_MS });
      latestId = id;
      return { run_id: id };
    },
  };
}
