import { describe, expect, it } from "vitest";
import { buildWhatIfRequest, draftFromOverride, leverageNote, SIZING_WORD } from "./whatIf";

describe("leverageNote: why a what-if can leave the curve where it was", () => {
  it("names proportional sizing, from the draft or from Settings' default", () => {
    expect(leverageNote("proportional", "fixed_margin")).toMatch(/^Proportional sizing mirrors their exposure ratio/);
    expect(leverageNote("", "proportional")).toMatch(/^Proportional sizing \(your Settings default\) mirrors/);
    expect(leverageNote("", "proportional")).toContain("Pick Fixed margin or Fixed notional to size by leverage.");
  });
  it("is silent for the other sizing modes and when the default is unknown", () => {
    expect(leverageNote("fixed_margin", "proportional")).toBeNull();
    expect(leverageNote("", "fixed_notional")).toBeNull();
    expect(leverageNote("", undefined)).toBeNull();
  });
  it("SIZING_WORD covers every Settings sizing mode", () => {
    expect(Object.keys(SIZING_WORD).sort()).toEqual(["allocation", "fixed_margin", "fixed_notional", "proportional"]);
  });
});

const TERMS = { sim_equity_usd: 250, allocation_usd: 250, exposure_mode: "target" as const, target_leverage: 20, margin_mode: "isolated" as const, max_worse_entry_pct: 10 };

describe("the what-if starts from the board's sim terms (invest $ at Nx), so a leverage change moves it", () => {
  it("seeds allocation, leverage, margin and worse-entry from the terms when no override is stored", () => {
    const d = draftFromOverride(null, 1000, TERMS);
    expect(d).toMatchObject({ equity: "250", sizing_mode: "allocation", allocation_usd: "250", target_leverage: "20", margin_mode: "isolated", max_worse_entry_pct: "10", leverage_mode: "" });
    const b = buildWhatIfRequest(d);
    expect(b).toEqual({ ok: true, body: { sim_equity_usd: 250, override: { sizing_mode: "allocation", allocation_usd: 250, exposure_mode: "target", target_leverage: 20, margin_mode: "isolated", max_worse_entry_pct: 10 } } });
  });
  it("follows their leverage when the terms say match", () => {
    const d = draftFromOverride(null, 1000, { ...TERMS, exposure_mode: "match", target_leverage: null });
    expect(d).toMatchObject({ sizing_mode: "allocation", target_leverage: "", leverage_mode: "match" });
    const b = buildWhatIfRequest(d);
    expect(b.ok && b.body.override).toMatchObject({ sizing_mode: "allocation", allocation_usd: 250 });
    expect(b.ok && b.body.override.exposure_mode).toBeUndefined();
  });
  it("a stored override wins over the terms, and the other sizing modes drop the allocation fields", () => {
    const d = draftFromOverride({ sizing_mode: "fixed_margin", fixed_margin_usd: 50, leverage_mode: "fixed", leverage: 5 }, 1000, TERMS);
    expect(d).toMatchObject({ equity: "1000", sizing_mode: "fixed_margin", fixed_margin_usd: "50", allocation_usd: "", target_leverage: "" });
    const b = buildWhatIfRequest({ ...d, allocation_usd: "250", target_leverage: "20" });
    expect(b.ok && b.body.override).toEqual({ sizing_mode: "fixed_margin", fixed_margin_usd: 50, leverage_mode: "fixed", leverage: 5 });
  });
  it("allocation mode validates the amount and the leverage", () => {
    const d = draftFromOverride(null, 1000, TERMS);
    expect(buildWhatIfRequest({ ...d, allocation_usd: "" })).toMatchObject({ ok: false, errors: { allocation_usd: "Invest at least $10.5" } });
    expect(buildWhatIfRequest({ ...d, allocation_usd: "5" })).toMatchObject({ ok: false });
    expect(buildWhatIfRequest({ ...d, target_leverage: "2.5" })).toMatchObject({ ok: false, errors: { target_leverage: expect.stringMatching(/whole number/) } });
  });
});
