import { describe, expect, it } from "vitest";
import { REVEAL_MAX_MS, revealDelays } from "./reveal";

describe("revealDelays", () => {
  it("staggers one batch by a fixed step, capped", () => {
    expect(revealDelays(4)).toEqual([0, 40, 80, 120]);
    expect(Math.max(...revealDelays(40))).toBe(REVEAL_MAX_MS);
    expect(revealDelays(0)).toEqual([]);
  });
});
