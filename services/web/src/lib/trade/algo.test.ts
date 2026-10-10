import { describe, expect, it } from "vitest";
import { algoWarning } from "./algo";
import { extractAddress } from "./pasteAddress";

describe("algo warning trigger", () => {
  it("fires on style algo, wallet style algo, or an hft flag (bare or with detail)", () => {
    expect(algoWarning({ style: "algo" })).toMatch(/copy latency/);
    expect(algoWarning({ walletStyle: "algo" })).not.toBeNull();
    expect(algoWarning({ flags: ["hft"] })).not.toBeNull();
    expect(algoWarning({ scoreFlags: ["hft:412/day"] })).not.toBeNull();
  });
  it("stays quiet for everyone else", () => {
    expect(algoWarning({ style: "swing", flags: ["vault", "hftx"] })).toBeNull();
    expect(algoWarning({})).toBeNull();
  });
});

describe("paste-address parsing", () => {
  const a = "0x" + "AbCd".repeat(10);
  it("bare, padded, quoted, and inside explorer links -> lower-cased address", () => {
    expect(extractAddress(a)).toBe(a.toLowerCase());
    expect(extractAddress(`  "${a}"\n`)).toBe(a.toLowerCase());
    expect(extractAddress(`https://app.hyperliquid.xyz/explorer/address/${a}`)).toBe(a.toLowerCase());
    expect(extractAddress(`https://hypurrscan.io/address/${a}#positions`)).toBe(a.toLowerCase());
    expect(extractAddress(`http://localhost:3000/?w=${a}&demo=1`)).toBe(a.toLowerCase());
  });
  it("refuses tx hashes, short hex, names, and two different addresses", () => {
    expect(extractAddress("0x" + "f".repeat(64))).toBeNull();
    expect(extractAddress("0x" + "f".repeat(39))).toBeNull();
    expect(extractAddress("Kestrel")).toBeNull();
    expect(extractAddress(`${a} 0x${"1".repeat(40)}`)).toBeNull();
    expect(extractAddress(`${a} ${a.toLowerCase()}`)).toBe(a.toLowerCase());
  });
});
