/**
 * The slice of EIP-1193 the sign-with-wallet flow uses, plus plain-words
 * error classification. No wallet library: MetaMask, Rabby and friends all
 * inject `window.ethereum`, and four RPC methods is all we call.
 */

export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] | Record<string, unknown> }): Promise<unknown>;
}

export type WalletErrorKind =
  | "no_wallet"
  | "rejected"
  | "wrong_account"
  | "pending"
  | "chain"
  | "api"
  | "unknown";

export class WalletFlowError extends Error {
  readonly kind: WalletErrorKind;
  constructor(kind: WalletErrorKind, message: string) {
    super(message);
    this.name = "WalletFlowError";
    this.kind = kind;
  }
}

/** The injected provider, or null (SSR, or no extension installed). */
export function injectedProvider(): Eip1193Provider | null {
  if (typeof window === "undefined") return null;
  const eth = (window as unknown as { ethereum?: Eip1193Provider }).ethereum;
  return eth && typeof eth.request === "function" ? eth : null;
}

function codeOf(err: unknown): number | null {
  if (!err || typeof err !== "object") return null;
  const e = err as { code?: unknown; cause?: unknown; data?: { originalError?: { code?: unknown } } };
  if (typeof e.code === "number") return e.code;
  if (typeof e.data?.originalError?.code === "number") return e.data.originalError.code;
  return e.cause ? codeOf(e.cause) : null;
}

/** EIP-1193 / JSON-RPC error codes -> what the user should know. */
export function classifyWalletError(err: unknown, during: "connect" | "switch" | "sign"): WalletFlowError {
  if (err instanceof WalletFlowError) return err;
  const code = codeOf(err);
  if (code === 4001) {
    const what = during === "connect" ? "connection request" : during === "switch" ? "network switch" : "signature";
    return new WalletFlowError("rejected", `You rejected the ${what} in your wallet. Nothing was approved.`);
  }
  if (code === -32002) return new WalletFlowError("pending", "Your wallet already has a request open. Open the extension and finish or dismiss it.");
  if (code === 4100) return new WalletFlowError("rejected", "Your wallet has not authorized this site. Unlock it and connect again.");
  if (code === 4902) return new WalletFlowError("chain", "Your wallet does not know the network this approval is signed on. Add it, then retry.");
  const msg = err instanceof Error ? err.message : typeof err === "string" ? err : "";
  return new WalletFlowError("unknown", msg || "The wallet returned an error.");
}

/** typed_data.domain.chainId as a number (wallets accept number, decimal or 0x string). */
export function domainChainId(typedData: Record<string, unknown>): number | null {
  const domain = typedData.domain as { chainId?: unknown } | undefined;
  const raw = domain?.chainId;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = raw.startsWith("0x") ? Number.parseInt(raw, 16) : Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export const toHexChain = (id: number) => `0x${id.toString(16)}`;

/** Networks we can offer to add when the wallet answers 4902. */
export const KNOWN_CHAINS: Record<number, { chainName: string; rpcUrls: string[]; blockExplorerUrls: string[] }> = {
  42161: { chainName: "Arbitrum One", rpcUrls: ["https://arb1.arbitrum.io/rpc"], blockExplorerUrls: ["https://arbiscan.io"] },
  421614: { chainName: "Arbitrum Sepolia", rpcUrls: ["https://sepolia-rollup.arbitrum.io/rpc"], blockExplorerUrls: ["https://sepolia.arbiscan.io"] },
};

export function chainName(id: number): string {
  return KNOWN_CHAINS[id]?.chainName ?? `chain ${id}`;
}

/** Lowercased 0x address list from eth_requestAccounts / eth_accounts. */
export function asAddresses(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").map((x) => x.toLowerCase()) : [];
}
