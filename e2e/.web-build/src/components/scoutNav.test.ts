import { describe, expect, it } from "vitest";
import { isScoutSection, SCOUT_TABS, scoutTabFor } from "./scoutNav";

describe("Scout tabs (custom sim discoverability)", () => {
  it("offers the custom sim (/discover) as a Scout tab", () => {
    expect(SCOUT_TABS.map((t) => t.href)).toEqual(["/scout", "/discover"]);
  });

  it("shows tabs on the leaderboard and the custom sim, not elsewhere", () => {
    expect(scoutTabFor("/scout")).toBe("/scout");
    expect(scoutTabFor("/discover")).toBe("/discover");
    expect(scoutTabFor("/scout/0xabc")).toBeNull();
    expect(scoutTabFor("/settings")).toBeNull();
    expect(scoutTabFor("/")).toBeNull();
    expect(scoutTabFor(null)).toBeNull();
  });

  it("keeps the top-level Scout item active on /discover", () => {
    expect(isScoutSection("/discover")).toBe(true);
    expect(isScoutSection("/scout")).toBe(true);
    expect(isScoutSection("/scout/0xabc")).toBe(true);
    expect(isScoutSection("/scouting")).toBe(false);
    expect(isScoutSection("/discovery")).toBe(false);
    expect(isScoutSection("/")).toBe(false);
  });
});
