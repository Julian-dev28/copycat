/**
 * `?demo=1` per-wallet log: a deterministic history for a wallet in the
 * demo book (opens at copy time, then adds, reduces, closes and the skips a
 * real engine logs), plus whatever the demo actions appended. Same clock and
 * same book = same log.
 */
import { normAddr } from "@/lib/address";
import type { EngineEvent } from "@/lib/api/types";
import { coinVerdict, VERDICT_TEXT } from "./coinFilter";
import { ourSide } from "./direction";
import type { WalletTerms } from "./fixtures";
import type { TraderPositionView } from "@/lib/scout/types";

const HOUR = 3_600_000;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** His positions -> what the engine would have logged for us since `investedMs`. Newest first. */
export function demoWalletHistory(
  address: string,
  his: TraderPositionView[],
  t: Pick<WalletTerms, "direction" | "allow" | "block" | "onlyNew">,
  investedMs: number,
  nowMs: number,
): EngineEvent[] {
  const a = normAddr(address);
  const out: EngineEvent[] = [];
  const h = hash(a);
  his.forEach((p, i) => {
    const ts = investedMs + (i + 1) * 47_000;
    if (ts > nowMs) return;
    const side = ourSide(p.side, t.direction);
    const v = coinVerdict(p.coin, t.allow, t.block);
    if (t.onlyNew) {
      out.push({ ts_ms: ts, action: "skip", leader: a, coin: p.coin, side, reason: "only new positions: they held it before you copied", dry_run: true });
      return;
    }
    if (v) {
      out.push({ ts_ms: ts, action: "skip", leader: a, coin: p.coin, side, reason: VERDICT_TEXT[v], dry_run: true });
      return;
    }
    const n = Math.max(10.5, Math.round((p.notional_usd / 2_000) * 100) / 100);
    out.push({
      ts_ms: ts, action: "open", leader: a, coin: p.coin, side, notional_usd: n, leverage: Math.max(1, Math.round(p.leverage)),
      reason: t.direction === "counter" ? "counter: opposite of their side" : null, dry_run: true,
    });
    // Then his activity on that coin every few hours: adds, a reduce, a worse-entry skip.
    const step = (3 + ((h >> i) % 5)) * HOUR;
    let k = 0;
    for (let at = ts + step; at < nowMs && k < 40; at += step, k++) {
      const pick = (h + i * 7 + k * 13) % 6;
      if (pick === 0 || pick === 3) out.push({ ts_ms: at, action: "add", leader: a, coin: p.coin, side, notional_usd: Math.round(n * 0.25 * 100) / 100, leverage: Math.max(1, Math.round(p.leverage)), dry_run: true });
      else if (pick === 1) out.push({ ts_ms: at, action: "reduce", leader: a, coin: p.coin, side, notional_usd: Math.round(n * 0.3 * 100) / 100, dry_run: true });
      else if (pick === 4) out.push({ ts_ms: at, action: "skip", leader: a, coin: p.coin, side, reason: "add skipped: mid 1.8% worse than their entry (max 1.5%)", dry_run: true });
    }
  });
  // A round trip he opened and closed after we started: always followed, even when paused or filtered.
  const rt = investedMs + 2 * HOUR + (h % 50) * 60_000;
  if (rt + 90 * 60_000 < nowMs) {
    const side = ourSide(h % 2 ? "long" : "short", t.direction);
    out.push({ ts_ms: rt, action: "open", leader: a, coin: "DOGE", side, notional_usd: 12.4, leverage: 5, dry_run: true });
    out.push({ ts_ms: rt + 90 * 60_000, action: "close", leader: a, coin: "DOGE", side, notional_usd: 12.4, reason: "they closed", dry_run: true });
  }
  return out.sort((x, y) => y.ts_ms - x.ts_ms);
}
