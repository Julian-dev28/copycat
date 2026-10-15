import { describe, expect, it } from "vitest";
import { leverageNote, SIZING_WORD } from "./whatIf";

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
