/**
 * Plain-words "why this score" for a Discover row. Mirrors
 * services/discovery/discovery/scoring.py exactly (same constants, same
 * order of penalties), so the explanation recomputes the score the api sent.
 * If scoring.py changes, scoreExplain.test.ts's parity cases must change too.
 *
 *   raw = sim_return_pct / max(5, |sim_max_drawdown_pct|)
 *   raw -= 50 per liquidation
 *   raw *= 0.2 if fewer than 5 copies
 */
import type { TraderScore } from "./api/types";
import { formatSignedPct, formatUsd } from "./format";

export const DRAWDOWN_FLOOR_PCT = 5;
export const LIQUIDATION_PENALTY = 50;
export const MIN_TRUSTED_COPIES = 5;
export const TOO_FEW_TRADES_DISCOUNT = 0.2;

/**
 * services/discovery/discovery/runner.py::_flagged_score gives wallets it
 * could not simulate (no opens in the window, fills/sim error) score=-1e9.
 * Anything at or below this threshold is "unscored", not a real ratio.
 */
export const UNSCORED_THRESHOLD = -1e8;

export function isUnscored(t: Pick<TraderScore, "score">): boolean {
  return t.score <= UNSCORED_THRESHOLD;
}

/** Score for display: "n/a" for the unscored sentinel. */
export function formatScore(t: Pick<TraderScore, "score">): string {
  return isUnscored(t) ? "n/a" : t.score.toFixed(2);
}

type Scorable = Pick<TraderScore, "sim_return_pct" | "sim_max_drawdown_pct" | "sim_liquidations" | "sim_copies">;

export function recomputeScore(t: Scorable): number {
  let raw = t.sim_return_pct / Math.max(DRAWDOWN_FLOOR_PCT, Math.abs(t.sim_max_drawdown_pct));
  if (t.sim_liquidations > 0) raw -= LIQUIDATION_PENALTY * t.sim_liquidations;
  if (t.sim_copies < MIN_TRUSTED_COPIES) raw *= TOO_FEW_TRADES_DISCOUNT;
  return raw;
}

export type ExplainTone = "good" | "bad" | "neutral";

export interface ExplainLine {
  tone: ExplainTone;
  text: string;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function explainScore(t: TraderScore, simEquityUsd: number): ExplainLine[] {
  if (isUnscored(t)) {
    const errored = t.flags.some((f) => f.startsWith("error"));
    return [
      {
        tone: "bad",
        text: errored
          ? "copycat couldn't simulate this wallet (a data error while reading its trades), so it has no score and sorts last."
          : `This wallet opened nothing copyable in the last 30 days (${plural(t.fills_30d, "fill", "fills")}), so there's nothing to simulate. No score, sorts last.`,
      },
    ];
  }
  const dd = Math.abs(t.sim_max_drawdown_pct);
  const ddUsed = Math.max(DRAWDOWN_FLOOR_PCT, dd);
  const ratio = t.sim_return_pct / ddUsed;
  const lines: ExplainLine[] = [];

  lines.push({
    tone: t.sim_return_pct > 0 ? "good" : t.sim_return_pct < 0 ? "bad" : "neutral",
    text: `Copying this wallet with ${formatUsd(simEquityUsd)} at your settings would have made ${formatSignedPct(
      t.sim_return_pct,
    )} over the last 30 days.`,
  });

  lines.push({
    tone: dd >= 30 ? "bad" : dd <= 10 ? "good" : "neutral",
    text:
      dd < DRAWDOWN_FLOOR_PCT
        ? `The worst dip along the way was only ${dd.toFixed(1)}%. Scoring treats anything under ${DRAWDOWN_FLOOR_PCT}% as ${DRAWDOWN_FLOOR_PCT}% so a lucky smooth ride can't blow the score up.`
        : `The worst dip along the way was ${dd.toFixed(1)}%. Return divided by that dip: ${t.sim_return_pct.toFixed(
            1,
          )} / ${ddUsed.toFixed(1)} = ${ratio.toFixed(2)}.`,
  });

  if (t.sim_liquidations > 0) {
    lines.push({
      tone: "bad",
      text: `${plural(t.sim_liquidations, "copy", "copies")} got liquidated. Each one costs ${LIQUIDATION_PENALTY} points, so this wallet can't outrank a steady one.`,
    });
  } else {
    lines.push({ tone: "good", text: "No copy got liquidated." });
  }

  if (t.sim_copies < MIN_TRUSTED_COPIES) {
    lines.push({
      tone: "bad",
      text: `Only ${plural(t.sim_copies, "copy", "copies")} opened. Under ${MIN_TRUSTED_COPIES} is too little data to trust, so the score is multiplied by ${TOO_FEW_TRADES_DISCOUNT}.`,
    });
  } else {
    lines.push({
      tone: "good",
      text: `${plural(t.sim_copies, "copy", "copies")} opened, enough to trust the numbers.`,
    });
  }

  if (t.sim_skipped_min_order > 0) {
    lines.push({
      tone: "neutral",
      text: `${plural(t.sim_skipped_min_order, "trade was", "trades were")} skipped for being under Hyperliquid's $10 minimum at your size.`,
    });
  }

  if (t.sim_fees_usd > 0) {
    lines.push({ tone: "neutral", text: `Fees paid in the sim: ${formatUsd(t.sim_fees_usd)} (already in the return).` });
  }

  return lines;
}

const FLAG_LABELS: Record<string, string> = {
  hft: "trades too fast to copy well",
  vault: "a vault, PnL is pooled",
  too_few_trades: "too few trades",
  liquidated: "a copy got liquidated",
  worse_entry: "entries skipped for slippage",
  margin_room: "skipped for lack of margin",
  max_open_copies: "hit the open-copies cap",
  no_candle_data: "missing price data",
  max_leverage_unknown: "unknown max leverage",
  error: "scoring error",
};

export interface FlagSummary {
  key: string;
  count: number;
  /** Plain-words meaning, for the tooltip/why panel. */
  meaning: string;
}

/**
 * Discovery emits per-coin flags like "worse_entry:BTC", "worse_entry:ETH"
 * and "error:fills:Timeout". Rendered raw they overflow the row; collapse
 * to one badge per kind with a count, in first-seen order.
 */
export function summarizeFlags(flags: string[]): FlagSummary[] {
  const out = new Map<string, FlagSummary>();
  for (const f of flags) {
    const key = f.split(":")[0];
    const prev = out.get(key);
    if (prev) prev.count += 1;
    else out.set(key, { key, count: 1, meaning: FLAG_LABELS[key] ?? key.replaceAll("_", " ") });
  }
  return [...out.values()];
}
