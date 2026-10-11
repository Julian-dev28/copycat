/** SignState -> the two visible steps (Connect wallet, Approve trading agent). Pure. */
import { shortenAddress } from "@/lib/format";
import { chainName } from "./eip1193";
import { phaseOf, type SignState } from "./signFlow";

export type StepState = "todo" | "doing" | "done" | "failed";

export interface SignStepView {
  title: string;
  detail?: string;
  state: StepState;
}

const APPROVE_DETAIL: Partial<Record<SignState["step"], string>> = {
  preparing: "Getting the approval from copycat…",
  signing: "Confirm the signature in your wallet. It approves a trading agent, it moves no funds.",
  submitting: "Registering the agent on Hyperliquid…",
};

export function signSteps(s: SignState): SignStepView[] {
  const phase = phaseOf(s);
  const failedIn = s.step === "error" ? s.error?.phase : null;

  const connect: SignStepView = {
    title: "Connect wallet",
    state: failedIn === "connect" ? "failed" : phase === "connect" ? (s.step === "connecting" ? "doing" : "todo") : "done",
    detail: failedIn === "connect"
      ? s.error?.message
      : s.address
        ? `Connected ${shortenAddress(s.address)}`
        : s.step === "connecting" ? "Approve the connection in your wallet…" : "MetaMask, Rabby or any browser wallet.",
  };

  let approveDetail = APPROVE_DETAIL[s.step];
  if (s.step === "switching") approveDetail = `Switch your wallet to ${chainName(s.targetChain ?? 0)} to sign. Hyperliquid approvals are signed there.`;
  if (failedIn === "approve") approveDetail = s.error?.message;
  if (phase === "done") approveDetail = "Agent approved. copycat can now trade this account.";

  const approve: SignStepView = {
    title: "Approve trading agent",
    state: failedIn === "approve" ? "failed" : phase === "done" ? "done" : phase === "approve" ? "doing" : "todo",
    detail: approveDetail ?? "One signature. No gas, no funds move.",
  };
  return [connect, approve];
}

export function isBusy(s: SignState): boolean {
  return s.step !== "idle" && s.step !== "done" && s.step !== "error";
}
