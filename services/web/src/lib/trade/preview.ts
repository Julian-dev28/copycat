/**
 * localPreview: the ticket's optimistic preview (see ticket.ts for the
 * formulas). Pure; the api preview replaces it when it answers.
 */
import { HL_MIN_ORDER_USD, MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { estimateLiquidationDistance } from "@/lib/liquidation";
import {
  ALLOCATION_SLACK, concentrate, DEFAULT_MAX_ORDER_VOLUME_PCT, rawCopies,
  type LiqEstimate, type PlannedCopy, type TicketInput, type TicketPreview,
} from "./ticket";

const MIN = HL_MIN_ORDER_USD;

/** The engine's exchange leverage (sizing.exchange_leverage): capped by max_position_leverage AND the coin's max (S8). */
function levFor(inp: TicketInput, hisLev: number, cap: number, coinMax?: number | null): number {
  const l = inp.mode === "target" ? inp.targetLeverage : Math.ceil(Math.max(1, hisLev));
  const c = coinMax && coinMax > 0 ? Math.min(cap, coinMax) : cap;
  return Math.max(1, Math.min(c, Math.round(l)));
}

export function localPreview(inp: TicketInput): TicketPreview {
  const cap = Math.max(1, Math.min(MAX_LEVERAGE_CAP, inp.maxPositionLeverage ?? MAX_LEVERAGE_CAP));
  const A = Math.max(0, inp.allocationUsd);
  const raw = rawCopies(inp);
  const total = raw.reduce((a, b) => a + b, 0);
  const gross = inp.positions.reduce((a, p) => a + Math.abs(p.notional_usd), 0);
  const hisLeverage = inp.leaderEquityUsd > 0 ? gross / inp.leaderEquityUsd : null;
  const levs = inp.positions.map((p) => levFor(inp, p.leverage, cap, p.max_leverage));

  let sized: number[];
  const reasons: (string | null)[] = raw.map(() => null);
  const bumped: boolean[] = raw.map(() => false);
  if (inp.smallMode === "concentrate") {
    sized = concentrate(raw, total, MIN);
    sized.forEach((s, i) => {
      if (s <= 0 && raw[i] > 0) reasons[i] = "under $10 min: moved to his bigger bets";
    });
  } else {
    sized = raw.map((r) => (r >= MIN ? r : 0));
    if (inp.smallMode === "bump") {
      let margin = sized.reduce((a, s, i) => a + s / levs[i], 0);
      const room = A * ALLOCATION_SLACK;
      const small = raw.map((r, i) => ({ r, i })).filter((x) => x.r > 0 && x.r < MIN).sort((a, b) => b.r - a.r);
      for (const { i } of small) {
        const m = MIN / levs[i];
        if (margin + m <= room + 1e-9) {
          sized[i] = MIN;
          bumped[i] = true;
          margin += m;
        } else reasons[i] = "under $10 min, no room to round up";
      }
    } else {
      raw.forEach((r, i) => {
        if (r > 0 && r < MIN) reasons[i] = "below $10 min, skipped";
      });
    }
  }

  const volPct = inp.maxOrderVolumePct ?? DEFAULT_MAX_ORDER_VOLUME_PCT;
  const copies: PlannedCopy[] = inp.positions.map((p, i) => {
    const notional = sized[i];
    const vol = inp.volume24hUsd?.[p.coin];
    const perOrder = vol && vol > 0 ? (vol * volPct) / 100 : Infinity;
    const status = notional <= 0 ? "skipped" : bumped[i] ? "bumped" : "copy";
    return {
      coin: p.coin,
      side: p.side,
      hisNotionalUsd: Math.abs(p.notional_usd),
      hisLeverage: p.leverage,
      notionalUsd: notional,
      leverage: levs[i],
      marginUsd: notional / levs[i],
      status,
      reason: status === "skipped" ? (reasons[i] ?? (A <= 0 ? "no amount yet" : "no size")) : bumped[i] ? "rounded up to the $10.50 minimum" : null,
      cycles: notional > 0 && Number.isFinite(perOrder) ? Math.max(1, Math.ceil(notional / perOrder)) : 1,
    };
  });

  const live = copies.filter((c) => c.status !== "skipped");
  const exposureUsd = live.reduce((a, c) => a + c.notionalUsd, 0);
  const smallest = inp.positions.reduce((m, p) => (Math.abs(p.notional_usd) > 0 ? Math.min(m, Math.abs(p.notional_usd)) : m), Infinity);
  let fullBookUsd: number | null = null;
  if (Number.isFinite(smallest) && gross > 0) {
    fullBookUsd = inp.mode === "target"
      ? (MIN * gross) / (smallest * Math.max(1, inp.targetLeverage))
      : inp.leaderEquityUsd > 0 ? (MIN * inp.leaderEquityUsd) / smallest : null;
  }
  const maxCycles = live.reduce((m, c) => Math.max(m, c.cycles), 1);

  return {
    copies,
    copied: live.length,
    total: inp.positions.length,
    exposureUsd,
    marginUsd: live.reduce((a, c) => a + c.marginUsd, 0),
    targetExposureUsd: inp.mode === "target" ? A * Math.max(1, inp.targetLeverage) : hisLeverage !== null ? A * hisLeverage : 0,
    hisLeverage,
    fullBookUsd,
    liq: liqEstimate(inp, live, exposureUsd, cap),
    liquidityCapped: maxCycles > 1,
    maxCycles,
    source: "local",
  };
}

/**
 * Isolated: the adverse move that liquidates one copy at the highest
 * leverage you'd run (lib/liquidation.ts). Cross: every copy shares your
 * equity, so roughly equity / total exposure, minus maintenance.
 */
export function liqEstimate(inp: TicketInput, live: PlannedCopy[], exposureUsd: number, cap: number): LiqEstimate {
  if (inp.marginMode === "cross") {
    const eq = inp.ourEquityUsd;
    const expo = exposureUsd + Math.max(0, inp.otherExposureUsd ?? 0);
    if (!eq || eq <= 0 || expo <= 0) return { kind: "unknown" };
    const pct = Math.max(0, (eq / expo - 1 / (2 * MAX_LEVERAGE_CAP)) * 100);
    return { kind: "cross", pct };
  }
  const lev = inp.mode === "target"
    ? Math.max(1, Math.min(cap, Math.round(inp.targetLeverage)))
    : live.reduce((m, c) => Math.max(m, c.leverage), 0);
  if (lev <= 0) return { kind: "unknown" };
  const pct = estimateLiquidationDistance(lev, "isolated").adverseMovePct ?? 0;
  return { kind: "isolated", pct, leverage: lev };
}

/**
 * Audit S8: the local estimate uses Scout's cached copy of his book, which can
 * be hours old. Say so whenever it is what the ticket shows, not only when
 * the engine preview failed.
 */
export function estimateNote(apiFailed: string | null | false, showingLocal: boolean, asOfMs: number | null | undefined, nowMs = Date.now()): string | null {
  const age = asOfMs ? ` (his positions as of ${ageText(nowMs - asOfMs)} ago)` : "";
  if (apiFailed === "too_old") return `Local estimate${age}: your api has no preview route yet.`;
  if (apiFailed) return `Local estimate${age}: the engine preview failed.`;
  if (showingLocal) return `Estimate from cached data${age}; the engine preview replaces it in a moment.`;
  return null;
}

function ageText(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} h` : `${Math.floor(h / 24)} d`;
}
