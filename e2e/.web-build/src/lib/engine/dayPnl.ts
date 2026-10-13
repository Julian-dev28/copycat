import type { EngineStatus } from "@/lib/api/types";
import { formatSignedUsd } from "@/lib/format";

export interface DayPnlView {
  /** The number to show, or "n/a" when there is none to trust. */
  text: string;
  tone: "up" | "down" | "flat" | "muted";
  /** False when the engine could not net out today's transfers (EngineStatus.day_pnl_reliable). */
  reliable: boolean;
  /** Tooltip explaining what the number is, or why it is held. */
  hint: string;
}

const NET = "Equity change since 00:00 UTC, deposits and withdrawals removed.";

/**
 * Day P&L as the status bar shows it. The engine nets transfers out of it
 * (engine/daypnl.py); when it could not (ledger read failed, a transfer still
 * settling) it sends day_pnl_reliable false and the last good value. Then the
 * number is muted and labeled "held", never colored like a fresh result.
 * Older apis omit the flag: treat as reliable.
 */
/** The engine's UNRELIABLE_GRACE_MS (services/engine/engine/core.py): with a loss limit set, new copies pause after this. */
export const UNRELIABLE_GRACE_MS = 60 * 60_000;

function utcHhMm(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
}

export function dayPnlView(
  status: Pick<EngineStatus, "day_pnl_usd" | "day_pnl_reliable" | "day_pnl_unreliable_since_ms">,
  lossLimitOn = false,
): DayPnlView {
  const v = status.day_pnl_usd;
  const reliable = status.day_pnl_reliable !== false;
  if (!reliable) {
    const since = status.day_pnl_unreliable_since_ms;
    const held = since ? `held since ${utcHhMm(since)}` : "held";
    const limit = lossLimitOn
      ? ` Your daily loss limit cannot see losses meanwhile: after ${UNRELIABLE_GRACE_MS / 60_000} min new copies pause until it can (exits continue).`
      : "";
    return {
      text: v === null || v === undefined ? `n/a (${held})` : `${formatSignedUsd(v)} (${held})`,
      tone: "muted",
      reliable,
      hint: `Could not net out today's deposits and withdrawals. Showing the last good value.${limit}`,
    };
  }
  const tone = v === null || v === undefined || v === 0 ? "flat" : v > 0 ? "up" : "down";
  return { text: formatSignedUsd(v ?? null), tone, reliable, hint: NET };
}
