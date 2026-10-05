/**
 * Pasted wallet addresses in the market search: a bare 0x address, one with
 * spaces or quotes, or an explorer link (app.hyperliquid.xyz, hypurrscan,
 * our own /?w= or /scout/0x... links). A 32-byte hash (a tx, 64 hex) is not
 * an address and is refused rather than truncated. Pure, tested.
 */
const HEX40 = /(?<![0-9a-fA-Fx])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])/g;

/** The one address in the text, lower-cased; null when there is none, or more than one distinct. */
export function extractAddress(text: string): string | null {
  const found = new Set((text.match(HEX40) ?? []).map((a) => a.toLowerCase()));
  return found.size === 1 ? [...found][0] : null;
}

