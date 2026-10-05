/**
 * A scripted EIP-1193 wallet for `?demo=1`, so the sign-with-wallet flow can
 * be walked without an extension. It signs for real (viem, a fixed demo key
 * that never holds funds), starts on Ethereum mainnet so the chain switch
 * step shows, and can be told to misbehave to exercise the error paths.
 */
import { privateKeyToAccount } from "viem/accounts";
import type { Eip1193Provider } from "./eip1193";

/** Hardhat's public test account #5: known to everyone, so never fund it. Demo only. */
const DEMO_WALLET_KEY = "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba" as const;
export const DEMO_WALLET_ADDRESS = privateKeyToAccount(DEMO_WALLET_KEY).address.toLowerCase();
export const DEMO_OTHER_ADDRESS = "0x5e1f00000000000000000000000000000000ca75";

export type DemoWalletMode = "approve" | "reject_sign" | "reject_connect" | "wrong_account" | "none";

export const DEMO_WALLET_MODES: { value: DemoWalletMode; label: string }[] = [
  { value: "approve", label: "Approves" },
  { value: "reject_sign", label: "Rejects signature" },
  { value: "reject_connect", label: "Rejects connect" },
  { value: "wrong_account", label: "Wrong account" },
  { value: "none", label: "Not installed" },
];

/** Demo USDC on Arbitrum in the fake wallet (6 decimals). */
export const DEMO_ARB_USDC = BigInt(250_000_000);
type DepositListener = (from: string, units: bigint) => void;
let onDeposit: DepositListener | null = null;
/** The demo account store listens here to credit a deposit, like Hyperliquid would. */
export function setDemoDepositListener(fn: DepositListener | null): void {
  onDeposit = fn;
}

const rejected = () => Object.assign(new Error("User rejected the request."), { code: 4001 });
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** `delayMs` 0 in tests. Each call to this makes a fresh wallet on chain 1. */
export function fakeWalletProvider(mode: DemoWalletMode, delayMs = 700): Eip1193Provider | null {
  if (mode === "none") return null;
  const signer = privateKeyToAccount(DEMO_WALLET_KEY);
  let chainId = 1;
  let balance = DEMO_ARB_USDC;
  const receipts = new Map<string, number>();
  const accounts = () => [mode === "wrong_account" ? DEMO_OTHER_ADDRESS : DEMO_WALLET_ADDRESS];
  return {
    async request({ method, params }) {
      const p = (Array.isArray(params) ? params : []) as unknown[];
      switch (method) {
        case "eth_requestAccounts":
          await wait(delayMs);
          if (mode === "reject_connect") throw rejected();
          return accounts();
        case "eth_accounts":
          return accounts();
        case "eth_chainId":
          return `0x${chainId.toString(16)}`;
        case "wallet_switchEthereumChain":
          await wait(delayMs / 2);
          chainId = Number.parseInt((p[0] as { chainId: string }).chainId, 16);
          return null;
        case "eth_signTypedData_v4": {
          await wait(delayMs);
          if (mode === "reject_sign") throw rejected();
          const td = JSON.parse(String(p[1])) as {
            domain: Record<string, unknown>; types: Record<string, { name: string; type: string }[]>; primaryType: string; message: Record<string, unknown>;
          };
          const { EIP712Domain: _domain, ...types } = td.types;
          return signer.signTypedData({ domain: td.domain, types, primaryType: td.primaryType, message: td.message } as Parameters<typeof signer.signTypedData>[0]);
        }
        case "eth_call": {
          // balanceOf(address) on any token: the demo wallet's USDC
          const word = balance.toString(16).padStart(64, "0");
          return `0x${word}`;
        }
        case "eth_sendTransaction": {
          await wait(delayMs);
          if (mode === "reject_sign") throw rejected();
          const tx = p[0] as { from: string; to: string; data: string };
          // transfer(address,uint256): selector + 32-byte address + 32-byte amount
          const units = BigInt(`0x${tx.data.slice(74, 138)}`);
          if (units > balance) throw Object.assign(new Error("transfer amount exceeds balance"), { code: -32603 });
          balance -= units;
          const hash = `0x${Date.now().toString(16).padStart(64, "0")}`;
          receipts.set(hash, 0);
          onDeposit?.(tx.from.toLowerCase(), units);
          return hash;
        }
        case "eth_getTransactionReceipt": {
          const hash = String(p[0]);
          const seen = (receipts.get(hash) ?? 0) + 1;
          receipts.set(hash, seen);
          return seen < 2 ? null : { transactionHash: hash, status: "0x1" };
        }
        default:
          throw Object.assign(new Error(`demo wallet does not support ${method}`), { code: 4200 });
      }
    },
  };
}
