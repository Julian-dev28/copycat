import { describe, expect, it } from "vitest";
import { exitDemoHref } from "./strip";

describe("exitDemoHref", () => {
  it("drops demo and acct and keeps the rest", () => {
    expect(exitDemoHref("/settings", "?demo=1&acct=small")).toBe("/settings");
    expect(exitDemoHref("/", "?demo=1&w=0xabc")).toBe("/?w=0xabc");
    expect(exitDemoHref(null, "")).toBe("/");
  });
});
