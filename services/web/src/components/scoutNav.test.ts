import { describe, expect, it } from "vitest";
import { isScoutSection } from "./scoutNav";

describe("Scout section active state", () => {
  it("is active on the leaderboard and the trader file, not elsewhere", () => {
    expect(isScoutSection("/scout")).toBe(true);
    expect(isScoutSection("/scout/0xabc")).toBe(true);
    expect(isScoutSection("/settings")).toBe(false);
    expect(isScoutSection("/")).toBe(false);
    expect(isScoutSection("/scouting")).toBe(false);
    expect(isScoutSection(null)).toBe(false);
  });
});
