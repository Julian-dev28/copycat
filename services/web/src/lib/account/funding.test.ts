import { describe, expect, it } from "vitest";
import {
  actionCap, actionProblem, balanceOfCalldata, decodeBalance, depositProblem, emptyForm, floorCents, isCredited, moveHint,
  parseUsd, signerPath, transferCalldata, usdToUnits, withdrawDestination, type ActionContext,
} from "./funding";
import type { FundingLimits } from "./types";

const OWN = `0x${"aa".repeat(20)}`;
const MINE = `0x${"bb".repeat(20)}`;
const OUT = `0x${"cc".repeat(20)}`;
const limits: FundingLimits = { abstraction: "default", unified: false, perps_withdrawable_usd: 100, spot_usdc_free_usd: 20 };
const ctx: ActionContext = { limits, feeUsd: 1, own: OWN, others: [MINE], needsPassphrase: false };
const form = (patch: Partial<ReturnType<typeof emptyForm>>) => ({ ...emptyForm(true), ...patch });

describe("amounts", () => {
  it("parses plain decimals only", () => {
    expect(parseUsd("12.5")).toBe(12.5);
    expect(parseUsd(" 5 ")).toBe(5);
    for (const bad of ["", "1e3", "-1", "1.1234567", "abc", "1,5"]) expect(parseUsd(bad)).toBeNull();
    expect(floorCents(0.119)).toBe(0.11);
  });
});

describe("depositProblem", () => {
  it("blocks below the minimum: such a deposit is lost", () => {
    expect(depositProblem("4.99", 100, 5)).toMatch(/minimum deposit is 5 USDC.*lost/);
    expect(depositProblem("5", 100, 5)).toBeNull();
  });
  it("blocks more than the wallet holds, and junk", () => {
    expect(depositProblem("101", 100, 5)).toMatch(/only holds/);
    expect(depositProblem("", 100, 5)).toBe("Enter an amount.");
    expect(depositProblem("1e3", 100, 5)).toMatch(/USDC amount/);
    expect(depositProblem("50", null, 5)).toBeNull();
  });
});

describe("actionProblem", () => {
  it("caps spot->perps by spot USDC, everything else by perps withdrawable", () => {
    expect(actionCap("usd_class_transfer", true, limits)).toBe(20);
    expect(actionCap("usd_class_transfer", false, limits)).toBe(100);
    expect(actionCap("withdraw", true, limits)).toBe(100);
    expect(actionCap("withdraw", true, null)).toBeNull();
    expect(actionProblem("usd_class_transfer", form({ amount: "21" }), ctx)).toMatch(/At most/);
    expect(actionProblem("usd_class_transfer", form({ amount: "20" }), ctx)).toBeNull();
    expect(actionProblem("usd_class_transfer", form({ amount: "0" }), ctx)).toMatch(/above 0/);
    expect(actionProblem("withdraw", form({ amount: "5" }), { ...ctx, limits: null })).toMatch(/could not be read/);
  });
  it("refuses a move on a unified account", () => {
    expect(actionProblem("usd_class_transfer", form({ amount: "1" }), { ...ctx, limits: { ...limits, unified: true } })).toMatch(/unified/);
  });
  it("withdraw: own address by default, any other needs the typed confirm, and more than the fee", () => {
    expect(withdrawDestination(form({}), OWN)).toBe(OWN);
    expect(actionProblem("withdraw", form({ amount: "5" }), ctx)).toBeNull();
    expect(actionProblem("withdraw", form({ amount: "1" }), ctx)).toMatch(/fee/);
    expect(actionProblem("withdraw", form({ amount: "5", destination: OUT }), ctx)).toMatch(/again in full/);
    expect(actionProblem("withdraw", form({ amount: "5", destination: OUT, confirm: `0x${"cd".repeat(20)}` }), ctx)).toMatch(/again in full/);
    expect(actionProblem("withdraw", form({ amount: "5", destination: OUT, confirm: OUT.toUpperCase().replace("0X", "0x") }), ctx)).toBeNull();
    expect(actionProblem("withdraw", form({ amount: "5", destination: OWN }), ctx)).toBeNull();
    expect(actionProblem("withdraw", form({ amount: "5", destination: "0x12" }), ctx)).toMatch(/not a 0x/);
  });
  it("send: only to another account in this copycat", () => {
    expect(actionProblem("usd_send", form({ amount: "5" }), ctx)).toMatch(/Pick one/);
    expect(actionProblem("usd_send", form({ amount: "5", destination: OWN }), ctx)).toMatch(/this account/);
    expect(actionProblem("usd_send", form({ amount: "5", destination: OUT }), ctx)).toMatch(/another account/);
    expect(actionProblem("usd_send", form({ amount: "5", destination: MINE }), ctx)).toBeNull();
  });
  it("passphrase path needs the passphrase", () => {
    expect(actionProblem("withdraw", form({ amount: "5" }), { ...ctx, needsPassphrase: true })).toMatch(/passphrase/);
  });
});

describe("hints and paths", () => {
  it("pushes Move when perps is ~0 and spot holds USDC (the $0.03 / $0.11 case)", () => {
    expect(moveHint({ perps_usd: 0.03 }, { ...limits, spot_usdc_free_usd: 0.11 })).toBe(true);
    expect(moveHint({ perps_usd: 50 }, limits)).toBe(false);
    expect(moveHint({ perps_usd: 0 }, { ...limits, spot_usdc_free_usd: 0 })).toBe(false);
    expect(moveHint({ perps_usd: 0 }, { ...limits, unified: true })).toBe(false);
    expect(moveHint({ perps_usd: 0 }, null)).toBe(false);
  });
  it("created -> passphrase; connected -> browser, or HL app without a wallet", () => {
    expect(signerPath({ kind: "created", has_main_key: true }, true)).toBe("passphrase");
    expect(signerPath({ kind: "connected_signed", has_main_key: false }, true)).toBe("browser");
    expect(signerPath({ kind: "connected_key", has_main_key: false }, false)).toBe("hl_app");
  });
  it("credits when the balance grew by the amount", () => {
    expect(isCredited(0.14, 25.14, 25)).toBe(true);
    expect(isCredited(0.14, 10, 25)).toBe(false);
  });
});

describe("erc20", () => {
  it("encodes transfer(bridge, units) and balanceOf exactly", () => {
    expect(usdToUnits("12.5")).toBe(BigInt(12_500_000));
    const data = transferCalldata("0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7", BigInt(5_000_000));
    expect(data).toBe("0xa9059cbb0000000000000000000000002df1c51e09aecf9cacb7bc98cb1742757f163df700000000000000000000000000000000000000000000000000000000004c4b40");
    expect(balanceOfCalldata(OWN).slice(0, 10)).toBe("0x70a08231");
    expect(decodeBalance(`0x${(BigInt(250_000_000)).toString(16).padStart(64, "0")}`)).toBe(BigInt(250_000_000));
    expect(() => decodeBalance("0x")).toThrow();
  });
});
