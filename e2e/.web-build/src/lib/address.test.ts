import { describe, expect, it } from "vitest";
import { explorerUrl, isValidAddress, normAddr } from "./address";

const ADDR = "0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa";

describe("address helpers", () => {
  it("normAddr trims and lowercases", () => {
    expect(normAddr("  0xABC ")).toBe("0xabc");
  });

  it("isValidAddress mirrors the contract regex", () => {
    expect(isValidAddress(ADDR.toUpperCase().replace("0X", "0x"))).toBe(true);
    expect(isValidAddress("0x123")).toBe(false);
  });

  it("explorerUrl points at the Hyperliquid explorer with a normalized address", () => {
    expect(explorerUrl(` ${ADDR.toUpperCase().replace("0X", "0x")} `)).toBe(
      `https://app.hyperliquid.xyz/explorer/address/${ADDR}`,
    );
  });
});
