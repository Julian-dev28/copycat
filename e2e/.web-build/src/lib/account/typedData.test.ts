import { describe, expect, it } from "vitest";
import { hashTypedData } from "viem";
import { userActionTypedData } from "./typedData";
import type { UserActionKind } from "./types";

// EIP-712 digests computed by services/hl (the Python SDK's field lists via
// hl.accounts.user_action_typed_data) for amount "2.5", nonce 1700000000000,
// signatureChainId 0xa4b1, destination 0x9999...: the demo builder must match byte for byte.
const SDK_DIGEST: Record<UserActionKind, string> = {
  usd_class_transfer: "0x6937d802a90c3802a176dc602ef4c885736b99ad833de655a9a261b4991de8d5",
  usd_send: "0x19ba3aef03b90405565c1b1b0a54251404073b917fa2203b10ca58aa49a67c26",
  withdraw: "0x56048d943d97ffabcbbceaea9cf9a20c3aad23620cd6aaa040e5bc17552891e7",
};

describe("userActionTypedData", () => {
  it.each(Object.keys(SDK_DIGEST) as UserActionKind[])("%s hashes exactly like the SDK", (kind) => {
    const { typed_data, action } = userActionTypedData(kind, "2.5", 1_700_000_000_000, { toPerp: true, destination: `0x${"99".repeat(20)}` }, "Mainnet");
    const { EIP712Domain: _d, ...types } = typed_data.types as Record<string, { name: string; type: string }[]>;
    const digest = hashTypedData({ domain: typed_data.domain as never, types, primaryType: typed_data.primaryType as string, message: typed_data.message as never });
    expect(digest).toBe(SDK_DIGEST[kind]);
    expect(action.signatureChainId).toBe("0xa4b1");
  });
});
