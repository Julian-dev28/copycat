/**
 * The fast-trader warning on the ticket: a wallet Scout classifies as algo,
 * or flags hft, trades faster than a poll-based copier can follow. Pure, tested.
 */
export const ALGO_WARNING =
  "This wallet trades like an algo. Fast traders' results usually don't survive copy latency: copycat reads his book every few seconds, so you enter later and at worse prices than he did.";

/** Flags arrive bare ("hft") or with a detail ("hft:412/day"). */
const hasHft = (flags: readonly string[] | null | undefined) => (flags ?? []).some((f) => f.split(":")[0].toLowerCase() === "hft");

export interface AlgoSignals {
  /** Scout's style for him (board row or trader file), or the api's WalletPosition.style. */
  style?: string | null;
  walletStyle?: string | null;
  flags?: readonly string[] | null;
  scoreFlags?: readonly string[] | null;
}

/** The warning text when he looks algorithmic, else null. */
export function algoWarning(s: AlgoSignals): string | null {
  const algo = s.style === "algo" || s.walletStyle === "algo" || hasHft(s.flags) || hasHft(s.scoreFlags);
  return algo ? ALGO_WARNING : null;
}
