import { describe, expect, it } from "vitest";
import { containerClass, containerFor } from "./container";
import { demoQuery, isItemActive, MOBILE_TABS, NAV_ITEMS } from "./nav";

describe("nav model", () => {
  it("desktop: Trade, Scout, Portfolio, Account, Settings", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual(["Trade", "Scout", "Portfolio", "Account", "Settings"]);
  });

  it("mobile tab bar has 4 labeled tabs; Settings lives in the account menu", () => {
    expect(MOBILE_TABS.map((i) => i.label)).toEqual(["Trade", "Scout", "Portfolio", "Account"]);
  });

  it("marks the active item, including sub-pages and Scout's Custom sim tab", () => {
    expect(isItemActive("/", "/")).toBe(true);
    expect(isItemActive("/", "/scout")).toBe(false);
    expect(isItemActive("/scout", "/scout/0xabc")).toBe(true);
    expect(isItemActive("/scout", "/discover")).toBe(true);
    expect(isItemActive("/account", "/account")).toBe(true);
    expect(isItemActive("/settings", "/settings")).toBe(true);
    expect(isItemActive("/portfolio", null)).toBe(false);
  });

  it("carries demo mode (and only demo params) across links", () => {
    expect(demoQuery("?demo=1&acct=small&w=0xabc")).toBe("?demo=1&acct=small");
    expect(demoQuery("?demo=1")).toBe("?demo=1");
    expect(demoQuery("?w=0xabc")).toBe("");
    expect(demoQuery("")).toBe("");
  });
});

describe("container", () => {
  it("Trade is wide, everything else reads at 72rem", () => {
    expect(containerFor("/")).toBe("wide");
    expect(containerFor("/scout")).toBe("read");
    expect(containerFor(null)).toBe("read");
    expect(containerClass("/")).toContain("max-w-[85rem]");
    expect(containerClass("/portfolio")).toContain("max-w-6xl");
  });
});
