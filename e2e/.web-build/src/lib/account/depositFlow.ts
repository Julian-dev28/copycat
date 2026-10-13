/**
 * Deposit from Arbitrum: an ERC-20 transfer of native USDC to Hyperliquid's
 * bridge, sent by the browser wallet. The bridge credits the address that
 * SENDS, so the wallet must be on the account's own address: anything else
 * would fund a different Hyperliquid account.
 *
 *   idle -> connecting -> [switching] -> reading -> ready
 *        -> confirming (wallet prompt) -> pending (tx hash, waiting for the receipt)
 *        -> confirmed (mined; Hyperliquid credits within ~1 minute) -> credited
 *
 * Every guard (amount >= min, <= balance, right wallet, right chain) runs again
 * right before eth_sendTransaction: the wallet can switch account or chain
 * while the dialog sits open.
 */
import { shortenAddress } from "@/lib/format";
import { asAddresses, classifyWalletError, WalletFlowError, type Eip1193Provider, type WalletErrorKind } from "./eip1193";
import { balanceOfCalldata, decodeBalance, depositProblem, parseUsd, transferCalldata, unitsToUsd, usdToUnits } from "./funding";
import { ensureChain } from "./signFlow";
import type { FundingInfo } from "./types";

export type DepositStep = "idle" | "connecting" | "switching" | "reading" | "ready" | "confirming" | "pending" | "confirmed" | "credited" | "error";

export interface DepositState {
  step: DepositStep;
  wallet: string | null;
  balanceUsd: number | null;
  amountUsd: number | null;
  txHash: string | null;
  error: { kind: WalletErrorKind | "blocked"; message: string } | null;
}

export type DepositEvent =
  | { type: "start" }
  | { type: "connected"; wallet: string }
  | { type: "switching"; targetChain: number }
  | { type: "reading" }
  | { type: "ready"; balanceUsd: number }
  | { type: "confirming"; amountUsd: number }
  | { type: "sent"; txHash: string }
  | { type: "confirmed" }
  | { type: "credited" }
  | { type: "fail"; kind: WalletErrorKind | "blocked"; message: string }
  | { type: "reset" };

export const initialDeposit: DepositState = { step: "idle", wallet: null, balanceUsd: null, amountUsd: null, txHash: null, error: null };

export function depositReducer(s: DepositState, e: DepositEvent): DepositState {
  switch (e.type) {
    case "start":
      return { ...initialDeposit, step: "connecting" };
    case "connected":
      return { ...s, wallet: e.wallet };
    case "switching":
      return { ...s, step: "switching" };
    case "reading":
      return { ...s, step: "reading" };
    case "ready":
      return { ...s, step: "ready", balanceUsd: e.balanceUsd, error: null };
    case "confirming":
      return { ...s, step: "confirming", amountUsd: e.amountUsd, error: null };
    case "sent":
      return { ...s, step: "pending", txHash: e.txHash };
    case "confirmed":
      return s.step === "pending" ? { ...s, step: "confirmed" } : s;
    case "credited":
      return s.step === "confirmed" ? { ...s, step: "credited" } : s;
    case "fail":
      return { ...s, step: "error", error: { kind: e.kind, message: e.message } };
    case "reset":
      return initialDeposit;
  }
}

/** After a failure before anything was sent, the user can fix the amount and retry. */
export const canRetrySend = (s: DepositState) => s.step === "error" && s.txHash === null && s.wallet !== null && s.balanceUsd !== null;

export interface DepositDeps {
  provider: Eip1193Provider | null;
  info: Pick<FundingInfo, "account_address" | "chain_id" | "chain_name" | "usdc_address" | "bridge_address" | "min_deposit_usd">;
  pollMs?: number;
  maxPolls?: number;
  sleep?: (ms: number) => Promise<void>;
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Audit L7: the only (chain, USDC, bridge) triples a deposit may use, pinned
 * here as well as in the api (services/hl/hl/accounts.py), so a wrong or
 * tampered api response can never point the transfer somewhere else.
 */
export const PINNED_BRIDGES: ReadonlyArray<{ chain_id: number; usdc: string; bridge: string }> = [
  { chain_id: 42161, usdc: "0xaf88d065e77c8cc2239327c5edb3a432268e5831", bridge: "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7" },
  { chain_id: 421614, usdc: "0x1baabb04529d43a73232b713c0fe471f7c7334d5", bridge: "0x08cfc1b6b2dcf36a1480b99353a354aa8ac56f89" },
];

export function bridgeIsPinned(info: Pick<FundingInfo, "chain_id" | "usdc_address" | "bridge_address">): boolean {
  return PINNED_BRIDGES.some((b) => b.chain_id === info.chain_id && b.usdc === info.usdc_address.toLowerCase() && b.bridge === info.bridge_address.toLowerCase());
}

function wrongWallet(wallet: string, own: string): WalletFlowError {
  return new WalletFlowError(
    "wrong_account",
    `Your wallet is on ${shortenAddress(wallet)}. Hyperliquid credits the address that sends to the bridge, so this deposit must come from ${shortenAddress(own)} itself. Switch to that account in your wallet, or use another deposit method.`,
  );
}

async function readBalance(provider: Eip1193Provider, deps: DepositDeps, own: string): Promise<number> {
  const raw = await provider.request({ method: "eth_call", params: [{ to: deps.info.usdc_address, data: balanceOfCalldata(own) }, "latest"] });
  return unitsToUsd(decodeBalance(raw));
}

/** Connect, require the account's own address, switch to Arbitrum, read the USDC balance. Never throws. */
export async function connectDeposit(deps: DepositDeps, dispatch: (e: DepositEvent) => void): Promise<boolean> {
  const { provider } = deps;
  if (!provider) {
    dispatch({ type: "fail", kind: "no_wallet", message: "No browser wallet found. Install MetaMask or Rabby and reload, or use another deposit method." });
    return false;
  }
  const own = deps.info.account_address.toLowerCase();
  if (!bridgeIsPinned(deps.info)) {
    dispatch({ type: "fail", kind: "blocked", message: "The deposit addresses from the api are not the known Hyperliquid bridge. Nothing was sent. Update copycat." });
    return false;
  }
  dispatch({ type: "start" });
  let phase: "connect" | "switch" = "connect";
  try {
    const accounts = asAddresses(await provider.request({ method: "eth_requestAccounts" }));
    if (!accounts.length) throw new WalletFlowError("rejected", "Your wallet did not share an account. Unlock it and retry.");
    if (!accounts.includes(own)) throw wrongWallet(accounts[0], own);
    dispatch({ type: "connected", wallet: own });
    phase = "switch";
    await ensureChain(provider, deps.info.chain_id, dispatch, "deposit from it");
    dispatch({ type: "reading" });
    dispatch({ type: "ready", balanceUsd: await readBalance(provider, deps, own) });
    return true;
  } catch (err) {
    const e = classifyWalletError(err, phase);
    dispatch({ type: "fail", kind: e.kind, message: e.message });
    return false;
  }
}

/**
 * Re-check, send the USDC transfer to the bridge, wait for the receipt.
 * Returns the tx hash once mined successfully, else null. Never throws.
 */
export async function sendDeposit(deps: DepositDeps, amountText: string, balanceUsd: number | null, dispatch: (e: DepositEvent) => void): Promise<string | null> {
  const { provider, info } = deps;
  const problem = bridgeIsPinned(info)
    ? depositProblem(amountText, balanceUsd, info.min_deposit_usd)
    : "The deposit addresses from the api are not the known Hyperliquid bridge. Nothing was sent.";
  if (problem || !provider) {
    dispatch({ type: "fail", kind: "blocked", message: problem ?? "No browser wallet found." });
    return null;
  }
  const own = info.account_address.toLowerCase();
  const sleep = deps.sleep ?? wait;
  let hash: string | null = null;
  try {
    const accounts = asAddresses(await provider.request({ method: "eth_accounts" }));
    if (accounts[0] !== own && !accounts.includes(own)) throw wrongWallet(accounts[0] ?? "another account", own);
    const chain = Number.parseInt(String(await provider.request({ method: "eth_chainId" })), 16);
    if (chain !== info.chain_id) throw new WalletFlowError("chain", `Your wallet left ${info.chain_name}. Switch back to it, then send.`);
    const fresh = await readBalance(provider, deps, own);
    const again = depositProblem(amountText, fresh, info.min_deposit_usd);
    if (again) throw new WalletFlowError("unknown", again);
    dispatch({ type: "confirming", amountUsd: parseUsd(amountText) ?? 0 });
    const tx = { from: own, to: info.usdc_address, data: transferCalldata(info.bridge_address, usdToUnits(amountText)) };
    const sent = await provider.request({ method: "eth_sendTransaction", params: [tx] });
    if (typeof sent !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(sent)) throw new WalletFlowError("unknown", "The wallet returned something that is not a transaction hash.");
    hash = sent;
    dispatch({ type: "sent", txHash: hash });
  } catch (err) {
    const e = classifyWalletError(err, "sign");
    const message = e.kind === "rejected" ? "You rejected the transfer in your wallet. Nothing was sent." : e.message;
    dispatch({ type: "fail", kind: e.kind, message });
    return null;
  }
  const maxPolls = deps.maxPolls ?? 150;
  for (let i = 0; i < maxPolls; i++) {
    let receipt: unknown = null;
    try {
      receipt = await provider.request({ method: "eth_getTransactionReceipt", params: [hash] });
    } catch {
      receipt = null; // a flaky RPC read is not a failed deposit: keep waiting
    }
    const status = receipt && typeof receipt === "object" ? (receipt as { status?: unknown }).status : undefined;
    if (status === "0x1" || status === 1) {
      dispatch({ type: "confirmed" });
      return hash;
    }
    if (status === "0x0" || status === 0) {
      dispatch({ type: "fail", kind: "unknown", message: "The transfer reverted on Arbitrum: no USDC left your wallet (only gas). Check the explorer, then retry." });
      return null;
    }
    await sleep(deps.pollMs ?? 2000);
  }
  dispatch({ type: "fail", kind: "pending", message: "No receipt yet. Check the transaction on the explorer BEFORE sending again, or you may deposit twice." });
  return null;
}
