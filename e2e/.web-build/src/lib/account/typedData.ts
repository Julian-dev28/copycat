/**
 * Hyperliquid's approveAgent EIP-712 payload, for the demo source only. In
 * live mode the api builds this (POST /api/accounts/approve/prepare) and the
 * browser passes it through untouched; the demo needs its own copy so the
 * fake wallet can sign and the demo store can verify the signature.
 * Shape per HL's user-signed actions: domain HyperliquidSignTransaction v1,
 * signatureChainId 0xa4b1 (Arbitrum One, 42161), zero verifying contract.
 */
import type { AgentApprovalPrepareResponse, UserActionKind, UserActionPrepareResponse } from "./types";

const CHAIN_ID = 42161;

export function approveAgentTypedData(
  agentAddress: string,
  agentName: string,
  nonce: number,
  hyperliquidChain: "Mainnet" | "Testnet",
): AgentApprovalPrepareResponse {
  const action = { type: "approveAgent", signatureChainId: `0x${CHAIN_ID.toString(16)}`, hyperliquidChain, agentAddress, agentName, nonce };
  return {
    action,
    nonce,
    typed_data: {
      domain: { name: "HyperliquidSignTransaction", version: "1", chainId: CHAIN_ID, verifyingContract: "0x0000000000000000000000000000000000000000" },
      types: {
        EIP712Domain: [
          { name: "name", type: "string" },
          { name: "version", type: "string" },
          { name: "chainId", type: "uint256" },
          { name: "verifyingContract", type: "address" },
        ],
        "HyperliquidTransaction:ApproveAgent": [
          { name: "hyperliquidChain", type: "string" },
          { name: "agentAddress", type: "address" },
          { name: "agentName", type: "string" },
          { name: "nonce", type: "uint64" },
        ],
      },
      primaryType: "HyperliquidTransaction:ApproveAgent",
      message: { hyperliquidChain, agentAddress, agentName, nonce },
    },
  };
}

// ── Funding actions (demo only; live mode gets these from .../action/prepare) ──

type Field = { name: string; type: string };
const UA: Record<UserActionKind, { type: string; primary: string; fields: Field[]; nonceField: "nonce" | "time" }> = {
  usd_class_transfer: {
    type: "usdClassTransfer", primary: "HyperliquidTransaction:UsdClassTransfer", nonceField: "nonce",
    fields: [{ name: "hyperliquidChain", type: "string" }, { name: "amount", type: "string" }, { name: "toPerp", type: "bool" }, { name: "nonce", type: "uint64" }],
  },
  usd_send: {
    type: "usdSend", primary: "HyperliquidTransaction:UsdSend", nonceField: "time",
    fields: [{ name: "hyperliquidChain", type: "string" }, { name: "destination", type: "string" }, { name: "amount", type: "string" }, { name: "time", type: "uint64" }],
  },
  withdraw: {
    type: "withdraw3", primary: "HyperliquidTransaction:Withdraw", nonceField: "time",
    fields: [{ name: "hyperliquidChain", type: "string" }, { name: "destination", type: "string" }, { name: "amount", type: "string" }, { name: "time", type: "uint64" }],
  },
};

/** Same field lists as the Python SDK (hyperliquid/utils/signing.py); typedData.test.ts pins the hashes. */
export function userActionTypedData(
  kind: UserActionKind,
  amount: string,
  nonce: number,
  opts: { toPerp?: boolean | null; destination?: string | null },
  hyperliquidChain: "Mainnet" | "Testnet",
): UserActionPrepareResponse {
  const spec = UA[kind];
  const action: Record<string, unknown> = { type: spec.type, amount, [spec.nonceField]: nonce, signatureChainId: `0x${CHAIN_ID.toString(16)}`, hyperliquidChain };
  if (kind === "usd_class_transfer") action.toPerp = Boolean(opts.toPerp);
  else action.destination = opts.destination;
  const message = Object.fromEntries(spec.fields.map((f) => [f.name, action[f.name]]));
  return {
    action,
    nonce,
    typed_data: {
      domain: { name: "HyperliquidSignTransaction", version: "1", chainId: CHAIN_ID, verifyingContract: "0x0000000000000000000000000000000000000000" },
      types: {
        EIP712Domain: [
          { name: "name", type: "string" },
          { name: "version", type: "string" },
          { name: "chainId", type: "uint256" },
          { name: "verifyingContract", type: "address" },
        ],
        [spec.primary]: spec.fields,
      },
      primaryType: spec.primary,
      message,
    },
  };
}
