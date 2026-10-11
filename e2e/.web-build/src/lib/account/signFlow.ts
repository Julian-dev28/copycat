/**
 * Sign-with-wallet: connect a browser wallet, approve a copycat trading
 * agent, hand the agent key to the api. Two user-visible phases:
 *
 *   1. Connect wallet          idle -> connecting
 *   2. Approve trading agent   preparing -> [switching] -> signing -> submitting -> done
 *
 * The agent private key is generated here, in the browser, lives in one
 * local variable of runSignFlow, and is sent once with /approve/submit. It
 * never enters SignState, React state, the query cache or a log. The typed
 * data from /approve/prepare goes to eth_signTypedData_v4 byte-for-byte
 * (JSON.stringify of exactly what the api returned).
 */
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { problemText } from "@/lib/trade/apiState";
import { shortenAddress } from "@/lib/format";
import {
  asAddresses, chainName, classifyWalletError, domainChainId, KNOWN_CHAINS, toHexChain,
  WalletFlowError, type Eip1193Provider, type WalletErrorKind,
} from "./eip1193";
import type { AgentApprovalPrepareRequest, AgentApprovalPrepareResponse, AgentApprovalSubmitRequest, TradingAccount } from "./types";

export type SignStep = "idle" | "connecting" | "preparing" | "switching" | "signing" | "submitting" | "done" | "error";
export type SignPhase = "connect" | "approve";

export interface SignState {
  step: SignStep;
  address: string | null;
  targetChain: number | null;
  error: { kind: WalletErrorKind; message: string; phase: SignPhase } | null;
  account: TradingAccount | null;
}

export type SignEvent =
  | { type: "start" }
  | { type: "connected"; address: string }
  | { type: "switching"; targetChain: number }
  | { type: "signing" }
  | { type: "submitting" }
  | { type: "done"; account: TradingAccount }
  | { type: "fail"; kind: WalletErrorKind; message: string }
  | { type: "reset" };

export const initialSign: SignState = { step: "idle", address: null, targetChain: null, error: null, account: null };

/** Which of the two steps a state belongs to (an error belongs to the step it failed in). */
export function phaseOf(s: SignState): SignPhase | "done" {
  if (s.step === "done") return "done";
  if (s.step === "error") return s.error?.phase ?? "connect";
  return s.step === "idle" || s.step === "connecting" ? "connect" : "approve";
}

export function signReducer(s: SignState, e: SignEvent): SignState {
  switch (e.type) {
    case "start":
      return { ...initialSign, step: "connecting" };
    case "connected":
      return { ...s, step: "preparing", address: e.address };
    case "switching":
      return { ...s, step: "switching", targetChain: e.targetChain };
    case "signing":
      return { ...s, step: "signing" };
    case "submitting":
      return { ...s, step: "submitting" };
    case "done":
      return { ...s, step: "done", account: e.account, error: null };
    case "fail": {
      const phase: SignPhase = s.step === "connecting" || s.step === "idle" ? "connect" : "approve";
      return { ...s, step: "error", error: { kind: e.kind, message: e.message, phase } };
    }
    case "reset":
      return initialSign;
  }
}

export interface SignDeps {
  provider: Eip1193Provider | null;
  label: string;
  /** Set when refreshing an existing account: the wallet must be on this address. */
  expectedAddress?: string | null;
  prepare: (req: AgentApprovalPrepareRequest) => Promise<AgentApprovalPrepareResponse>;
  submit: (req: AgentApprovalSubmitRequest) => Promise<TradingAccount>;
  /** Injected in tests; defaults to viem's CSPRNG key. */
  newAgentKey?: () => `0x${string}`;
}

const SIG_RE = /^0x[0-9a-fA-F]{130}$/;

function apiFail(err: unknown, what: string): WalletFlowError {
  const text = problemText(err, what);
  const tooOld = text.startsWith("Your api has no");
  return new WalletFlowError("api", tooOld ? `api too old: ${text}` : text);
}

/** Switch the wallet to `target` (adding Arbitrum if it answers 4902). Shared by every wallet flow. */
export async function ensureChain(
  provider: Eip1193Provider,
  target: number,
  dispatch: (e: { type: "switching"; targetChain: number }) => void,
  purpose = "sign this approval",
): Promise<void> {
  const current = Number.parseInt(String(await provider.request({ method: "eth_chainId" })), 16);
  if (current === target) return;
  dispatch({ type: "switching", targetChain: target });
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId: toHexChain(target) }] });
  } catch (err) {
    const known = KNOWN_CHAINS[target];
    const e = classifyWalletError(err, "switch");
    if (e.kind !== "chain" || !known) throw e;
    try {
      await provider.request({ method: "wallet_addEthereumChain", params: [{ chainId: toHexChain(target), ...known, nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 } }] });
    } catch (addErr) {
      throw classifyWalletError(addErr, "switch");
    }
  }
  const after = Number.parseInt(String(await provider.request({ method: "eth_chainId" })), 16);
  if (after !== target) throw new WalletFlowError("chain", `Switch your wallet to ${chainName(target)} to ${purpose}.`);
}

/** Runs the whole flow, reporting each transition through `dispatch`. Never throws. */
export async function runSignFlow(deps: SignDeps, dispatch: (e: SignEvent) => void): Promise<TradingAccount | null> {
  const { provider } = deps;
  if (!provider) {
    dispatch({ type: "fail", kind: "no_wallet", message: "No browser wallet found. Install MetaMask or Rabby and reload, or use the API key tab." });
    return null;
  }
  dispatch({ type: "start" });
  let phase: "connect" | "switch" | "sign" = "connect";
  try {
    const accounts = asAddresses(await provider.request({ method: "eth_requestAccounts" }));
    if (!accounts.length) throw new WalletFlowError("rejected", "Your wallet did not share an account. Unlock it and retry.");
    const expected = deps.expectedAddress?.toLowerCase() ?? null;
    const address = expected && accounts.includes(expected) ? expected : accounts[0];
    if (expected && address !== expected) {
      throw new WalletFlowError("wrong_account", `Your wallet is on ${shortenAddress(address)}, but this account is ${shortenAddress(expected)}. Switch accounts in your wallet and retry.`);
    }
    dispatch({ type: "connected", address });

    let agentKey: `0x${string}` | null = (deps.newAgentKey ?? generatePrivateKey)();
    const agentAddress = privateKeyToAccount(agentKey).address;
    let prepared: AgentApprovalPrepareResponse;
    try {
      prepared = await deps.prepare({ main_address: address, agent_address: agentAddress, agent_name: "copycat" });
    } catch (err) {
      throw apiFail(err, "agent approval");
    }

    const target = domainChainId(prepared.typed_data);
    phase = "switch";
    if (target !== null) await ensureChain(provider, target, dispatch);

    dispatch({ type: "signing" });
    phase = "sign";
    const signature = await provider.request({ method: "eth_signTypedData_v4", params: [address, JSON.stringify(prepared.typed_data)] });
    if (typeof signature !== "string" || !SIG_RE.test(signature)) throw new WalletFlowError("unknown", "The wallet returned something that is not a signature.");

    dispatch({ type: "submitting" });
    let account: TradingAccount;
    try {
      account = await deps.submit({ label: deps.label, main_address: address, agent_private_key: agentKey, action: prepared.action, nonce: prepared.nonce, signature });
    } catch (err) {
      throw apiFail(err, "agent approval");
    } finally {
      agentKey = null;
    }
    dispatch({ type: "done", account });
    return account;
  } catch (err) {
    const e = classifyWalletError(err, phase);
    dispatch({ type: "fail", kind: e.kind, message: e.message });
    return null;
  }
}
