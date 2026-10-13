import { describe, expect, it } from "vitest";
import { dayPnlView } from "./dayPnl";

describe("dayPnlView", () => {
  it("colors a reliable number", () => {
    expect(dayPnlView({ day_pnl_usd: 12.5, day_pnl_reliable: true }).tone).toBe("up");
    expect(dayPnlView({ day_pnl_usd: -3, day_pnl_reliable: true }).tone).toBe("down");
    expect(dayPnlView({ day_pnl_usd: 0, day_pnl_reliable: true }).tone).toBe("flat");
  });

  it("treats an older api without the flag as reliable", () => {
    const v = dayPnlView({ day_pnl_usd: 5 });
    expect(v.reliable).toBe(true);
    expect(v.tone).toBe("up");
  });

  it("mutes and labels an unreliable number as held", () => {
    const v = dayPnlView({ day_pnl_usd: -10, day_pnl_reliable: false });
    expect(v.reliable).toBe(false);
    expect(v.tone).toBe("muted");
    expect(v.text).toContain("(held)");
    expect(v.hint).toMatch(/deposits and withdrawals/);
  });

  it("shows n/a when unreliable with no good value yet", () => {
    expect(dayPnlView({ day_pnl_usd: null, day_pnl_reliable: false }).text).toBe("n/a (held)");
  });

  it("says since when it is held (S5) and warns about the loss limit only when one is set", () => {
    const since = Date.UTC(2026, 9, 14, 7, 5);
    const v = dayPnlView({ day_pnl_usd: -10, day_pnl_reliable: false, day_pnl_unreliable_since_ms: since }, true);
    expect(v.text).toBe("-$10.00 (held since 07:05 UTC)");
    expect(v.hint).toMatch(/after 60 min new copies pause/);
    expect(dayPnlView({ day_pnl_usd: 1, day_pnl_reliable: false, day_pnl_unreliable_since_ms: since }).hint)
      .not.toMatch(/loss limit/);
  });
});
