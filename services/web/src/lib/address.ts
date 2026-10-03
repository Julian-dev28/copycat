/** Mirrors contracts.models.norm_addr / the `_ADDR` validator regex. */

const ADDR_RE = /^0x[0-9a-f]{40}$/;

export function normAddr(address: string): string {
  return address.trim().toLowerCase();
}

export function isValidAddress(address: string): boolean {
  return ADDR_RE.test(normAddr(address));
}

/** Hyperliquid's public explorer page for a wallet. */
export function explorerUrl(address: string): string {
  return `https://app.hyperliquid.xyz/explorer/address/${normAddr(address)}`;
}
