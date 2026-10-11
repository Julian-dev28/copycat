import { describe, expect, it } from "vitest";
import { exitDemoHref, routeHasOwnDemoBanner } from "./strip";

describe("routeHasOwnDemoBanner", () => {
  it("is true only where a page draws its own banner", () => {
    expect(routeHasOwnDemoBanner("/")).toBe(true);
    expect(routeHasOwnDemoBanner("/scout")).toBe(true);
    expect(routeHasOwnDemoBanner("/scout/0xabc")).toBe(true);
    for (const r of ["/settings", "/discover", "/account", "/portfolio", "/scoutx", null]) {
      expect(routeHasOwnDemoBanner(r)).toBe(false);
    }
  });
});

describe("exitDemoHref", () => {
  it("drops demo and acct and keeps the rest", () => {
    expect(exitDemoHref("/settings", "?demo=1&acct=small")).toBe("/settings");
    expect(exitDemoHref("/", "?demo=1&w=0xabc")).toBe("/?w=0xabc");
    expect(exitDemoHref(null, "")).toBe("/");
  });
});
