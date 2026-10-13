import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import { plan } from "./fixtures";
import { formatCountdown, livePlans, planOutcome, planTerms, secondsLeft, spacedCode } from "./pendingPlans";


describe("countdown", () => {
  it("counts whole seconds down to zero and never below", () => {
    expect(secondsLeft(plan(), 1_000)).toBe(300);
    expect(secondsLeft(plan(), 300_500)).toBe(0);
    expect(secondsLeft(plan(), 999_999)).toBe(0);
  });
  it("formats m:ss", () => {
    expect(formatCountdown(300)).toBe("5:00");
    expect(formatCountdown(9)).toBe("0:09");
    expect(formatCountdown(-4)).toBe("0:00");
  });
});

describe("livePlans", () => {
  it("drops plans expired between polls and sorts newest first", () => {
    const a = plan({ plan_id: "a", created_ms: 1, expires_ms: 500 });
    const b = plan({ plan_id: "b", created_ms: 2, expires_ms: 5_000 });
    const c = plan({ plan_id: "c", created_ms: 3, expires_ms: 5_000 });
    expect(livePlans([a, b, c], 1_000).map((p) => p.plan_id)).toEqual(["c", "b"]);
    expect(livePlans(undefined, 0)).toEqual([]);
  });
  it("treats expires_ms == now as expired, like the api", () => {
    expect(livePlans([plan({ expires_ms: 10 })], 10)).toEqual([]);
  });
});

describe("terms", () => {
  it("says the same terms the MCP shows Claude", () => {
    expect(planTerms(plan())).toBe("$50.00 at 3x, copying their side, entries within 2%, following new positions");
    expect(planTerms(plan({ leverage: null, trade_direction: "counter", follow: false })))
      .toBe("$50.00 at trader's leverage, countering their side, entries within 2%, one-shot");
  });
  it("spaces a 6-char code for reading and leaves others alone", () => {
    expect(spacedCode("K7QX2M")).toBe("K7Q X2M");
    expect(spacedCode("ABC")).toBe("ABC");
  });
  it("warns before approval when nothing will trade or execute is refused", () => {
    expect(planOutcome(plan()).tone).toBe("accent");
    expect(planOutcome(plan({ trading_live: false })).text).toMatch(/places no orders/);
    expect(planOutcome(plan({ executable: false, trading_live: false })).tone).toBe("danger");
  });
});

describe("api.getPendingMcpPlans", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("is a GET to /api/mcp/plans/pending", async () => {
    const fetchMock = vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.getPendingMcpPlans()).resolves.toEqual([]);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
    expect(url).toMatch(/\/api\/mcp\/plans\/pending$/);
    expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
  });
});
