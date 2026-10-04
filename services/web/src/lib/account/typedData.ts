/**
 * Hyperliquid's approveAgent EIP-712 payload, for the demo source only. In
 * live mode the api builds this (POST /api/accounts/approve/prepare) and the
 * browser passes it through untouched; the demo needs its own copy so the
 * fake wallet can sign and the demo store can verify the signature.
 * Shape per HL's user-signed actions: domain HyperliquidSignTransaction v1,
 * signatureChainId 0xa4b1 (Arbitrum One, 42161), zero verifying contract.
 */
import type { AgentApprovalPrepareResponse } from "./types";

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
