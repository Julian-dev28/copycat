import { describe, expect, it } from "vitest";
import { nextRovingIndex } from "./rovingKeys";

describe("nextRovingIndex", () => {
  it("moves with arrows and wraps", () => {
    expect(nextRovingIndex("ArrowRight", 0, 3)).toBe(1);
    expect(nextRovingIndex("ArrowRight", 2, 3)).toBe(0);
    expect(nextRovingIndex("ArrowLeft", 0, 3)).toBe(2);
    expect(nextRovingIndex("ArrowDown", 1, 3)).toBe(2);
    expect(nextRovingIndex("ArrowUp", 1, 3)).toBe(0);
  });

  it("jumps with Home and End", () => {
    expect(nextRovingIndex("Home", 2, 4)).toBe(0);
    expect(nextRovingIndex("End", 0, 4)).toBe(3);
  });

  it("skips disabled items", () => {
    const off = (i: number) => i === 1;
    expect(nextRovingIndex("ArrowRight", 0, 3, off)).toBe(2);
    expect(nextRovingIndex("ArrowLeft", 2, 3, off)).toBe(0);
    expect(nextRovingIndex("Home", 2, 3, (i) => i === 0)).toBe(1);
  });

  it("ignores other keys and empty groups", () => {
    expect(nextRovingIndex("Enter", 0, 3)).toBeNull();
    expect(nextRovingIndex("ArrowRight", 0, 0)).toBeNull();
    expect(nextRovingIndex("ArrowRight", 0, 2, () => true)).toBeNull();
  });
});
