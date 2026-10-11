import { describe, expect, it } from "vitest";
import { changedDigits } from "./numberFlow";

describe("changedDigits", () => {
  it("marks nothing when equal", () => {
    expect([...changedDigits("$1,204.10", "$1,204.10")]).toEqual([]);
  });

  it("marks only the digits that moved, aligned right", () => {
    expect([...changedDigits("$1,204.10", "$1,204.35")]).toEqual([7, 8]);
  });

  it("marks new leading characters when the value grows", () => {
    // "$10.01" vs " $9.99" right-aligned: only the "." stays put
    expect([...changedDigits("$9.99", "$10.01")]).toEqual([0, 1, 2, 4, 5]);
  });

  it("handles a sign flip", () => {
    expect(changedDigits("+$5.00", "-$5.00")).toEqual(new Set([0]));
  });
});
