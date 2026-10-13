import { describe, expect, it } from "vitest";
import {
  actionSummary,
  allocationBreakdown,
  copyColumnTitle,
  copyRowState,
  disabledReason,
  effectiveLeverageText,
  fullBookShortfall,
  leverageMismatch,
  leverageMismatchText,
  liqText,
  liqTone,
} from "./ticketView";

describe("allocationBreakdown (#10)", () => {
  it("splits the allocation into margin now and reserved, with exposure", () => {
    expect(allocationBreakdown(100, { marginUsd: 13.94, exposureUsd: 217.96 })).toEqual({ marginNowUsd: 13.94, exposureUsd: 217.96, reservedUsd: 86.06 });
  });
  it("never reserves a negative amount (margin can run 2% over)", () => {
    expect(allocationBreakdown(100, { marginUsd: 102, exposureUsd: 500 })?.reservedUsd).toBe(0);
  });
  it("is null without an amount or a preview", () => {
    expect(allocationBreakdown(null, { marginUsd: 1, exposureUsd: 2 })).toBeNull();
    expect(allocationBreakdown(0, { marginUsd: 1, exposureUsd: 2 })).toBeNull();
    expect(allocationBreakdown(100, null)).toBeNull();
  });
});

describe("fullBookShortfall (#10)", () => {
  it("says what it needs and what you have when the full copy exceeds equity", () => {
    const s = fullBookShortfall(47.2, 20);
    expect(s).toMatchObject({ needUsd: 48, haveUsd: 20 });
    expect(s?.text).toBe("Copying all their positions needs $48.00; you have $20.00.");
  });
  it("is null when it fits or a number is unknown", () => {
    expect(fullBookShortfall(48, 1000)).toBeNull();
    expect(fullBookShortfall(null, 20)).toBeNull();
    expect(fullBookShortfall(48, undefined)).toBeNull();
  });
});

describe("effectiveLeverageText (#3)", () => {
  it("shows the cap when Settings lowers the leverage", () => {
    expect(effectiveLeverageText(25, 15)).toBe("25x → 15x cap");
  });
  it("shows the plain value when not capped or the cap is unknown", () => {
    expect(effectiveLeverageText(10, 15)).toBe("10x");
    expect(effectiveLeverageText(15, 15)).toBe("15x");
    expect(effectiveLeverageText(25, null)).toBe("25x");
    expect(effectiveLeverageText(null, 15)).toBe("n/a");
  });
});

describe("copyRowState (#5)", () => {
  const held = new Set(["BTC"]);
  it("would copy when you do not copy this trader", () => {
    expect(copyRowState(false, held, "BTC")).toBe("would");
  });
  it("held when you hold that coin's copy, next trade otherwise", () => {
    expect(copyRowState(true, held, "BTC")).toBe("held");
    expect(copyRowState(true, held, "ETH")).toBe("next");
  });
  it("column title follows whether money is in", () => {
    expect(copyColumnTitle(true)).toBe("Your copy");
    expect(copyColumnTitle(false)).toBe("Would copy");
  });
});

describe("action bar summary (#8)", () => {
  it("one line: exposure, margin, liq with a tone", () => {
    expect(actionSummary({ exposureUsd: 217.96, marginUsd: 13.94, liq: { kind: "isolated", pct: 1.5, leverage: 40 } })).toEqual([
      { label: "Exposure", value: "$217.96" },
      { label: "Margin", value: "$13.94" },
      { label: "Liq", value: "~1.5%", tone: "danger" },
    ]);
    expect(actionSummary(null)).toEqual([]);
  });
  it("liq tone: under 10% danger, under 25% warn, else muted", () => {
    expect(liqTone({ kind: "isolated", pct: 9.9, leverage: 10 })).toBe("danger");
    expect(liqTone({ kind: "cross", pct: 24 })).toBe("warn");
    expect(liqTone({ kind: "cross", pct: 40 })).toBe("muted");
    expect(liqTone({ kind: "unknown" })).toBe("muted");
    expect(liqText({ kind: "isolated", pct: 0.42, leverage: 50 })).toBe("~0.42%");
  });
  it("disabled reason names the missing step", () => {
    const base = { hasBody: false, action: "copy" as const, pending: false, custom: true, amountText: "", error: null };
    expect(disabledReason(base)).toBe("Enter an amount");
    expect(disabledReason({ ...base, amountText: "5", error: "Minimum $10" })).toBe("Minimum $10");
    expect(disabledReason({ ...base, hasBody: true })).toBeNull();
    expect(disabledReason({ ...base, hasBody: true, action: "unchanged" })).toBe("Nothing changed yet");
  });
});

describe("leverageMismatch (user_consensus_2026-10-14.md P0 #4)", () => {
  it("warns when your cushion is tighter than theirs, and flags it severe past half their cushion", () => {
    // leader effective 3x: ~32.3% cushion. You at 10x: 9.0% cushion (exactly the research doc's example).
    const m = leverageMismatch({ kind: "isolated", pct: 9, leverage: 10 }, 3, "target");
    expect(m).not.toBeNull();
    expect(m!.theirLeverage).toBe(3);
    expect(m!.theirPct).toBeCloseTo(32.33, 1);
    expect(m!.severe).toBe(true);
    expect(leverageMismatchText(m!)).toBe(
      "You liquidate on a ~9.0% move; they run an effective 3.0x (~32.3% cushion). A move they'd survive could wipe your copy.",
    );
  });
  it("is tighter but not severe once your cushion is still over half of theirs", () => {
    const m = leverageMismatch({ kind: "isolated", pct: 24, leverage: 4 }, 3, "target");
    expect(m?.severe).toBe(false);
  });
  it("is null once your cushion is as wide as theirs or wider", () => {
    expect(leverageMismatch({ kind: "isolated", pct: 49, leverage: 2 }, 3, "target")).toBeNull();
  });
  it("is null for cross margin (no single comparable number) or an unknown/zero leader leverage", () => {
    expect(leverageMismatch({ kind: "cross", pct: 10 }, 3, "target")).toBeNull();
    expect(leverageMismatch({ kind: "unknown" }, 3, "target")).toBeNull();
    expect(leverageMismatch({ kind: "isolated", pct: 9, leverage: 10 }, null, "target")).toBeNull();
    expect(leverageMismatch({ kind: "isolated", pct: 9, leverage: 10 }, 0, "target")).toBeNull();
  });
  it("is null in match mode even where the numbers would otherwise be severe: each copy already opens at the leader's own per-coin leverage there", () => {
    expect(leverageMismatch({ kind: "isolated", pct: 9, leverage: 10 }, 3, "match")).toBeNull();
  });
});
