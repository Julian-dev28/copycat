/** Deterministic display formatting. No JSX, no state — pure string functions. */

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatUsd(value: number | null | undefined, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return compact ? usdCompact.format(value) : usd.format(value);
}

export function formatSignedUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${usd.format(value)}`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function formatSignedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatLeverage(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value}x`;
}

export function shortenAddress(address: string, lead = 6, trail = 4): string {
  if (address.length <= lead + trail + 2) return address;
  return `${address.slice(0, lead)}…${address.slice(-trail)}`;
}

/** "3s ago" / "4m ago" / "2h ago" style relative time, for status/event timestamps. */
export function formatAgo(ms: number | null | undefined, nowMs: number = Date.now()): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  const deltaS = Math.max(0, Math.round((nowMs - ms) / 1000));
  if (deltaS < 1) return "just now";
  if (deltaS < 60) return `${deltaS}s ago`;
  const deltaM = Math.round(deltaS / 60);
  if (deltaM < 60) return `${deltaM}m ago`;
  const deltaH = Math.round(deltaM / 60);
  if (deltaH < 24) return `${deltaH}h ago`;
  const deltaD = Math.round(deltaH / 24);
  return `${deltaD}d ago`;
}

export function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

/**
 * Prices span 6 orders of magnitude on Hyperliquid (BTC ~1e5, kPEPE ~1e-2,
 * some memecoins ~1e-5). Two fixed decimals would print $0.00 for those, so
 * use 5 significant digits under $1 and cap at 2 decimals at or above $1.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs === 0) return "$0";
  if (abs >= 1) {
    return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `$${value.toLocaleString("en-US", { maximumSignificantDigits: 5 })}`;
}

/** Position size: absolute, at most 6 significant decimals, no float noise like 0.30000000000000004. */
export function formatSize(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.abs(value).toLocaleString("en-US", { maximumSignificantDigits: 6 });
}
