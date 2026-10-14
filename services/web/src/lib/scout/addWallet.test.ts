import { describe, expect, it } from "vitest";
import { addedText, BAD_INPUT, EMPTY_INPUT, parseWalletInput, shortAddr } from "./addWallet";

const A = "0x" + "ab".repeat(20);

describe("parseWalletInput", () => {
  it("takes a bare address, with spaces, quotes or mixed case", () => {
    expect(parseWalletInput(A)).toEqual({ address: A });
    expect(parseWalletInput(`  "${A.toUpperCase().replace("0X", "0x")}" `)).toEqual({ address: A });
  });

  it("takes an explorer link or one of our own links", () => {
    expect(parseWalletInput(`https://app.hyperliquid.xyz/explorer/address/${A}`)).toEqual({ address: A });
    expect(parseWalletInput(`http://localhost:3000/scout/${A}?demo=1`)).toEqual({ address: A });
  });

  it("refuses empty, short, non-hex and two-address input with a message", () => {
    expect(parseWalletInput("")).toEqual({ error: EMPTY_INPUT });
    expect(parseWalletInput("   ")).toEqual({ error: EMPTY_INPUT });
    expect(parseWalletInput("0x1234")).toEqual({ error: BAD_INPUT });
    expect(parseWalletInput("vitalik.eth")).toEqual({ error: BAD_INPUT });
    expect(parseWalletInput("0x" + "g".repeat(40))).toEqual({ error: BAD_INPUT });
    expect(parseWalletInput(`${A} ${"0x" + "cd".repeat(20)}`)).toEqual({ error: BAD_INPUT });
    // a 32-byte tx hash is not an address and must not be truncated to one
    expect(parseWalletInput("0x" + "ab".repeat(32))).toEqual({ error: BAD_INPUT });
  });
});

describe("shortAddr and addedText", () => {
  it("shortens to 0x1234…abcd, lower-cased", () => {
    expect(shortAddr(A.toUpperCase().replace("0X", "0x"))).toBe("0xabab…abab");
    expect(shortAddr("0xabc")).toBe("0xabc");
  });

  it("says whether the file is still being built", () => {
    expect(addedText(A, true)).toBe("Added 0xabab…abab to Scout, building its file");
    expect(addedText(A, false)).toBe("0xabab…abab is on the Scout board");
  });
});
