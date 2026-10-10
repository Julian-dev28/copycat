import { describe, expect, it } from "vitest";
import { checkAmount, chipAmount, maxInvest, parseInvest, targetLeverageCap } from "./form";

describe("amounts from $10 to $10M", () => {
  it("parses plain, comma, $ and k/m suffixes", () => {
    expect(parseInvest("1,000")).toBe(1000);
    expect(parseInvest("$2.5k")).toBe(2500);
    expect(parseInvest("10m")).toBe(10_000_000);
    expect(parseInvest("")).toBeNull();
    expect(parseInvest("abc")).toBeNull();
    expect(parseInvest("-5")).toBeNull();
  });

  it("max = free margin + this wallet's own margin, floored to cents", () => {
    expect(maxInvest(100.129)).toBe(100.12);
    expect(maxInvest(40, 10)).toBe(50);
    expect(maxInvest(null)).toBeNull();
    expect(maxInvest(-5)).toBe(0);
  });

  it("chips are % of max, floored, Max is exactly max", () => {
    expect(chipAmount(1_000_000, 25)).toBe(250_000);
    expect(chipAmount(20.01, 75)).toBe(15);
    expect(chipAmount(20.01, 100)).toBe(20.01);
    expect(chipAmount(0, 50)).toBeNull();
  });

  it("checkAmount: blank and tiny are errors, over free margin is a warning", () => {
    expect(checkAmount(null, 100)).toEqual({ ok: false, error: "Enter an amount" });
    expect(checkAmount(0.5, 100).ok).toBe(false);
    expect(checkAmount(150, 100)).toMatchObject({ ok: true, warn: expect.stringMatching(/free margin/) });
    expect(checkAmount(100, 100)).toEqual({ ok: true, warn: null });
  });
});

describe("ticket leverage cap (max_position_leverage)", () => {
  it("over the cap: capped, opens at the cap", () => {
    expect(targetLeverageCap(50, 20)).toEqual({ set: 50, effective: 20, capped: true, cap: 20 });
  });
  it("at or under the cap: as set", () => {
    expect(targetLeverageCap(20, 20)).toMatchObject({ effective: 20, capped: false });
    expect(targetLeverageCap(5, 50)).toMatchObject({ effective: 5, capped: false });
  });
  it("unknown cap = the hard 50x; junk clamps", () => {
    expect(targetLeverageCap(60, undefined)).toMatchObject({ set: 50, effective: 50, capped: false, cap: 50 });
    expect(targetLeverageCap(Number.NaN, 10)).toMatchObject({ set: 1, effective: 1 });
  });
  it("mirrors components/copy/leverageCap fixedLeverageCap: min(set, cap)", () => {
    for (const [l, c] of [[3, 2], [10, 10], [1, 50], [49, 7]]) expect(targetLeverageCap(l, c).effective).toBe(Math.min(l, c));
  });
});
