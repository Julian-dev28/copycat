/**
 * Contract v8 coin filters: "Only these coins" (allowlist) and "Never these
 * coins" (blocklist). Same rule as services/engine/engine/sizing.py
 * coin_allowed: case-insensitive, a HIP-3 coin keeps its "dex:COIN" form,
 * a non-empty allowlist admits only its coins, the blocklist always wins.
 * Filters gate opens and adds only; exits are never filtered. The engine
 * skips a filtered slice (it does not re-spread its dollars). Pure, tested.
 */
import type { PlannedCopy, TicketPreview } from "./ticket";

/** Comparison key, like engine norm_coin. */
export const coinKey = (c: string): string => String(c).trim().toLowerCase();

/** Common Hyperliquid perps, for autocomplete when the board hasn't loaded. */
export const COMMON_COINS = [
  "BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "SUI", "AVAX", "LINK", "BNB", "ADA", "LTC", "TON", "ENA", "WIF", "kPEPE", "kBONK",
  "FARTCOIN", "TRUMP", "AAVE", "ARB", "OP", "TIA", "SEI", "NEAR", "APT", "INJ", "PENDLE", "ONDO", "TAO", "xyz:TSLA", "xyz:NVDA",
  "xyz:XYZ100", "xyz:GOLD",
];

/**
 * The display form of a typed coin: the known spelling when one matches
 * ("kpepe" -> "kPEPE"), else upper case with a lower-case dex prefix
 * ("XYZ:tsla" -> "xyz:TSLA"). Null for blank or junk.
 */
export function canonicalCoin(input: string, known: readonly string[] = []): string | null {
  const t = input.trim().replace(/^\$/, "");
  if (!t || !/^[A-Za-z0-9]+(:[A-Za-z0-9]+)?$/.test(t)) return null;
  const hit = known.find((k) => coinKey(k) === coinKey(t));
  if (hit) return hit;
  const [a, b] = t.split(":");
  return b === undefined ? a.toUpperCase() : `${a.toLowerCase()}:${b.toUpperCase()}`;
}

/** Add a coin to a list (deduped case-insensitively). Returns the same list when it adds nothing. */
export function addCoin(list: readonly string[], input: string, known: readonly string[] = []): string[] {
  const c = canonicalCoin(input, known);
  if (!c || list.some((x) => coinKey(x) === coinKey(c))) return [...list];
  return [...list, c];
}

/** "BTC, eth  sol" -> ["BTC", "ETH", "SOL"]: pasting several at once. */
export function parseCoins(text: string, known: readonly string[] = []): string[] {
  return text.split(/[\s,;]+/).reduce<string[]>((acc, t) => addCoin(acc, t, known), []);
}

export type FilterVerdict = null | "not_allowed" | "blocked";

/** Why a coin is filtered out, or null when it may be copied. */
export function coinVerdict(coin: string, allow: readonly string[], block: readonly string[]): FilterVerdict {
  const k = coinKey(coin);
  if (block.some((b) => coinKey(b) === k)) return "blocked";
  const a = allow.filter((x) => x.trim());
  if (a.length && !a.some((x) => coinKey(x) === k)) return "not_allowed";
  return null;
}

export const VERDICT_TEXT: Record<Exclude<FilterVerdict, null>, string> = {
  not_allowed: "filtered: not in Only these coins",
  blocked: "filtered: on Never these coins",
};

/**
 * Mark the slices your filters drop as skipped (reason says which list) and
 * recompute the totals. Idempotent: an api preview that already skipped
 * them just gets the plain-words reason.
 */
export function applyCoinFilter(p: TicketPreview, allow: readonly string[], block: readonly string[]): TicketPreview {
  if (!allow.length && !block.length) return p;
  const copies: PlannedCopy[] = p.copies.map((c) => {
    const v = coinVerdict(c.coin, allow, block);
    if (!v) return c;
    return { ...c, status: "skipped", notionalUsd: 0, marginUsd: 0, reason: VERDICT_TEXT[v], filtered: true, cycles: 1 };
  });
  const live = copies.filter((c) => c.status !== "skipped");
  const maxCycles = live.reduce((m, c) => Math.max(m, c.cycles), 1);
  return {
    ...p,
    copies,
    copied: live.length,
    exposureUsd: live.reduce((a, c) => a + c.notionalUsd, 0),
    marginUsd: live.reduce((a, c) => a + c.marginUsd, 0),
    maxCycles,
    liquidityCapped: maxCycles > 1,
  };
}

/**
 * Autocomplete: his coins first (what he actually trades), then the wider
 * list, prefix matches before substring matches, minus what's already chosen.
 */
export function suggestCoins(query: string, hisCoins: readonly string[], allCoins: readonly string[], chosen: readonly string[], limit = 8): { coin: string; his: boolean }[] {
  const q = coinKey(query);
  const taken = new Set(chosen.map(coinKey));
  const seen = new Set<string>();
  const pool: { coin: string; his: boolean }[] = [];
  for (const [list, his] of [[hisCoins, true], [allCoins, false]] as const) {
    for (const c of list) {
      const k = coinKey(c);
      if (!k || seen.has(k) || taken.has(k)) continue;
      seen.add(k);
      pool.push({ coin: c, his });
    }
  }
  const score = (c: string) => {
    const k = coinKey(c);
    const bare = k.includes(":") ? k.split(":")[1] : k;
    if (!q) return 0;
    if (k.startsWith(q) || bare.startsWith(q)) return 0;
    if (k.includes(q)) return 1;
    return -1;
  };
  return pool
    .map((x, i) => ({ x, s: score(x.coin), i }))
    .filter((y) => y.s >= 0)
    .sort((a, b) => a.s - b.s || Number(b.x.his) - Number(a.x.his) || a.i - b.i)
    .slice(0, limit)
    .map((y) => y.x);
}
