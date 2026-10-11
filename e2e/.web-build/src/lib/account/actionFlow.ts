/**
 * Move (spot <-> perps), Send and Withdraw: Hyperliquid user-signed actions
 * that only the account's MAIN key can sign.
 *
 *   passphrase (created accounts): submitting -> done     (POST .../action, the vault signs)
 *   browser    (connected):        connecting -> preparing -> [switching] -> signing -> submitting -> done
 *
 * The browser path requires the wallet to be on the account's own address
 * (the api rejects any other signer anyway; failing here saves a signature).
 * The typed data from .../action/prepare goes to eth_signTypedData_v4
 * untouched. The passphrase never enters ActionState.
 */
import { shortenAddress } from "@/lib/format";
import { accountErrorText } from "./errors";
import { asAddresses, classifyWalletError, domainChainId, WalletFlowError, type Eip1193Provider, type WalletErrorKind } from "./eip1193";
import type { SignerPath } from "./funding";
import { ensureChain } from "./signFlow";
import type {
  UserActionPrepareRequest, UserActionPrepareResponse, UserActionResult, UserActionRunRequest, UserActionSubmitRequest,
} from "./types";

export type ActionStep = "idle" | "connecting" | "preparing" | "switching" | "signing" | "submitting" | "done" | "error";

export interface ActionState {
  step: ActionStep;
  result: UserActionResult | null;
  error: { kind: WalletErrorKind; message: string } | null;
}

export type ActionEvent =
  | { type: "connecting" }
  | { type: "preparing" }
  | { type: "switching"; targetChain: number }
  | { type: "signing" }
  | { type: "submitting" }
  | { type: "done"; result: UserActionResult }
  | { type: "fail"; kind: WalletErrorKind; message: string }
  | { type: "reset" };

export const initialAction: ActionState = { step: "idle", result: null, error: null };

export function actionReducer(s: ActionState, e: ActionEvent): ActionState {
  switch (e.type) {
    case "connecting":
    case "preparing":
    case "signing":
    case "submitting":
      return { ...s, step: e.type, error: null };
    case "switching":
      return { ...s, step: "switching" };
    case "done":
      return { step: "done", result: e.result, error: null };
    case "fail":
      return { ...s, step: "error", error: { kind: e.kind, message: e.message } };
    case "reset":
      return initialAction;
  }
}

export const isBusy = (s: ActionState) => !["idle", "done", "error"].includes(s.step);

export interface ActionDeps {
  path: SignerPath;
  accountId: string;
  /** The account's main address: the only signer the api accepts. */
  own: string;
  provider: Eip1193Provider | null;
  prepare: (id: string, req: UserActionPrepareRequest) => Promise<UserActionPrepareResponse>;
  submit: (id: string, req: UserActionSubmitRequest) => Promise<UserActionResult>;
  run: (id: string, req: UserActionRunRequest) => Promise<UserActionResult>;
}

const SIG_RE = /^0x[0-9a-fA-F]{130}$/;

function apiFail(err: unknown): WalletFlowError {
  return new WalletFlowError("api", accountErrorText(err, "funding"));
}

/** Runs one action end to end, reporting through `dispatch`. Never throws. */
export async function runAction(
  deps: ActionDeps,
  req: UserActionPrepareRequest,
  passphrase: string | null,
  dispatch: (e: ActionEvent) => void,
): Promise<UserActionResult | null> {
  if (deps.path === "hl_app") {
    dispatch({ type: "fail", kind: "no_wallet", message: "No browser wallet found. Do this on app.hyperliquid.xyz with the wallet that owns this account." });
    return null;
  }
  if (deps.path === "passphrase") {
    dispatch({ type: "submitting" });
    try {
      const result = await deps.run(deps.accountId, { ...req, passphrase: passphrase ?? "" });
      dispatch({ type: "done", result });
      return result;
    } catch (err) {
      dispatch({ type: "fail", kind: "api", message: apiFail(err).message });
      return null;
    }
  }
  const { provider } = deps;
  if (!provider) {
    dispatch({ type: "fail", kind: "no_wallet", message: "No browser wallet found. Install MetaMask or Rabby and reload." });
    return null;
  }
  const own = deps.own.toLowerCase();
  let phase: "connect" | "switch" | "sign" = "connect";
  try {
    dispatch({ type: "connecting" });
    const accounts = asAddresses(await provider.request({ method: "eth_requestAccounts" }));
    if (!accounts.length) throw new WalletFlowError("rejected", "Your wallet did not share an account. Unlock it and retry.");
    if (!accounts.includes(own)) {
      throw new WalletFlowError("wrong_account", `Your wallet is on ${shortenAddress(accounts[0])}, but only ${shortenAddress(own)} can sign for this account. Switch accounts in your wallet and retry.`);
    }
    dispatch({ type: "preparing" });
    let prepared: UserActionPrepareResponse;
    try {
      prepared = await deps.prepare(deps.accountId, req);
    } catch (err) {
      throw apiFail(err);
    }
    phase = "switch";
    const target = domainChainId(prepared.typed_data);
    if (target !== null) await ensureChain(provider, target, dispatch, "sign this");
    phase = "sign";
    dispatch({ type: "signing" });
    const signature = await provider.request({ method: "eth_signTypedData_v4", params: [own, JSON.stringify(prepared.typed_data)] });
    if (typeof signature !== "string" || !SIG_RE.test(signature)) throw new WalletFlowError("unknown", "The wallet returned something that is not a signature.");
    dispatch({ type: "submitting" });
    let result: UserActionResult;
    try {
      result = await deps.submit(deps.accountId, { kind: req.kind, action: prepared.action, nonce: prepared.nonce, signature, confirm_destination: req.confirm_destination ?? null });
    } catch (err) {
      throw apiFail(err);
    }
    dispatch({ type: "done", result });
    return result;
  } catch (err) {
    const e = classifyWalletError(err, phase);
    const message = e.kind === "rejected" && phase === "sign" ? "You rejected the signature in your wallet. Nothing moved." : e.message;
    dispatch({ type: "fail", kind: e.kind, message });
    return null;
  }
}
