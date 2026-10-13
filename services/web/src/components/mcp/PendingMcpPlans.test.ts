import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { McpPendingPlan } from "@/lib/api/types";
import { plan } from "@/lib/mcp/fixtures";
import { PendingMcpPlans } from "./PendingMcpPlans";

vi.mock("@/context/AuthContext", () => ({ useAuth: () => ({ hasToken: true }) }));

function render(plans: McpPendingPlan[] | undefined, enabled = true): string {
  const qc = new QueryClient();
  if (plans) qc.setQueryData(["mcp-plans-pending"], plans);
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: qc }, createElement(PendingMcpPlans, { enabled })));
}

describe("PendingMcpPlans", () => {
  const now = Date.now();
  const live = plan({ created_ms: now, expires_ms: now + 240_000 });

  it("shows the confirm code, the terms and the expiry for a live plan", () => {
    const html = render([live]);
    expect(html).toContain("Pending MCP plans");
    expect(html).toContain("K7Q X2M");
    expect(html).toContain("$50.00 at 3x");
    expect(html).toMatch(/expires in [34]:\d\d/);
    expect(html).toContain("plan_0123456789abcdef");
  });

  it("renders nothing with no plans, only expired ones, or in demo", () => {
    expect(render([])).toBe("");
    expect(render([plan({ expires_ms: now - 1 })])).toBe("");
    expect(render(undefined)).toBe("");
    expect(render([live], false)).toBe("");
  });

  it("flags a plan that would place no orders", () => {
    expect(render([{ ...live, trading_live: false }])).toContain("places no orders");
  });
});
