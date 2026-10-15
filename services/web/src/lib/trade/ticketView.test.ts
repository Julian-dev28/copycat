import { describe, expect, it } from "vitest";
import type { PlannedCopy } from "./ticket";
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
  sizeStarved,
  skipReasonShort,
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

describe("skipped rows say why (2026-10-15: a $15 account read 'skipped' on every position)", () => {
  it("shortens the engine's reasons for the cell, keeps unknown ones", () => {
    expect(skipReasonShort("copy $0.04 under the $10.5 minimum")).toBe("$0.04 < $10.50 min");
    expect(skipReasonShort("slice $9.40 under the $10.5 minimum")).toBe("$9.40 < $10.50 min");
    expect(skipReasonShort("concentrate: slice $9.40 under the $10.5 minimum, allocation goes to their bigger positions")).toBe("folded into their bigger positions");
    expect(skipReasonShort("under $10 min: moved to their bigger bets")).toBe("folded into their bigger positions");
    expect(skipReasonShort("only_new_positions: their current positions are not copied")).toBe("new trades only");
    expect(skipReasonShort("one-shot: only the positions they held when copied")).toBe("one-shot: not held when copied");
    expect(skipReasonShort("liquidity cap $8.00 is under the $10.5 minimum")).toBe("liquidity cap");
    expect(skipReasonShort("below $10 min, skipped")).toBe("< $10.50 min");
    expect(skipReasonShort("no amount yet")).toBe("no amount yet");
    expect(skipReasonShort(null)).toBe("skipped");
    expect(skipReasonShort("x".repeat(60))).toHaveLength(42);
  });
});

function skipped(coin: string, hisNotionalUsd: number, reason: string, extra: Partial<PlannedCopy> = {}): PlannedCopy {
  return { coin, side: "long", hisNotionalUsd, hisLeverage: 5, notionalUsd: 0, leverage: 15, marginUsd: 0, status: "skipped", reason, cycles: 1, ...extra };
}

describe("sizeStarved: every position under the minimum, and the terms that work", () => {
  // the live case: proportional Settings sizing, 19% of $15.21 spread by their weights
  const book = [skipped("BTC", 327_138, "copy $1.50 under the $10.5 minimum"), skipped("ZRO", 30_763, "copy $0.04 under the $10.5 minimum")];

  it("global sizing on a $15 account: names the cause and offers this ticket's own terms", () => {
    const s = sizeStarved({ copies: book, total: 2 }, { global: true, amount: null, leverage: 15, cap: 15, equityUsd: 15.21 });
    expect(s?.text).toBe("Your Settings sizing comes out under Hyperliquid's $10.50 minimum on every position at $15.21 of equity. Give this ticket its own amount and leverage.");
    // $15 x 1x = $15; their biggest position is 91% of the book: $13.70 clears $10.50 at 1x
    expect(s?.fix).toEqual({ amountText: "15", leverage: 1, label: "Invest $15.00 at 1x" });
  });

  it("global sizing with a book spread thin: the leverage that clears it, capped", () => {
    const thin = [1, 2, 3, 4, 5].map((i) => skipped(`C${i}`, 100, "copy $0.50 under the $10.5 minimum"));   // 20% each: needs $52.50 of exposure
    expect(sizeStarved({ copies: thin, total: 5 }, { global: true, amount: null, leverage: 15, cap: 15, equityUsd: 15.21 })?.fix)
      .toEqual({ amountText: "15", leverage: 4, label: "Invest $15.00 at 4x" });
    const s = sizeStarved({ copies: thin, total: 5 }, { global: true, amount: null, leverage: 15, cap: 3, equityUsd: 15.21 });
    expect(s?.fix).toBeNull();
    expect(s?.text).toContain("Even $15.00 at the 3x cap is under it on their biggest position; it takes $18.00.");
    expect(sizeStarved({ copies: thin, total: 5 }, { global: true, amount: null, leverage: 15, cap: 15, equityUsd: null })).toEqual({
      text: "Your Settings sizing comes out under Hyperliquid's $10.50 minimum on every position. Give this ticket its own amount and leverage.", fix: null,
    });
  });

  it("custom terms: the leverage that works, or the amount at the cap, or the honest dead end", () => {
    const thin = [1, 2, 3, 4, 5].map((i) => skipped(`C${i}`, 100, "slice $0.50 under the $10.5 minimum"));
    expect(sizeStarved({ copies: thin, total: 5 }, { global: false, amount: 15, leverage: 1, cap: 15, equityUsd: 15.21 })).toEqual({
      text: "At $15.00 x 1x nothing clears Hyperliquid's $10.50 minimum order. 4x puts their biggest position over it.",
      fix: { amountText: "15", leverage: 4, label: "Use 4x" },
    });
    expect(sizeStarved({ copies: thin, total: 5 }, { global: false, amount: 2, leverage: 3, cap: 3, equityUsd: 100 })).toEqual({
      text: "At $2.00 x 3x nothing clears Hyperliquid's $10.50 minimum order. $18.00 at the 3x cap puts their biggest position over it.",
      fix: { amountText: "18", leverage: 3, label: "Invest $18.00 at 3x" },
    });
    expect(sizeStarved({ copies: thin, total: 5 }, { global: false, amount: 2, leverage: 3, cap: 3, equityUsd: 15.21 })).toEqual({
      text: "At $2.00 x 3x nothing clears Hyperliquid's $10.50 minimum order; even the 3x cap needs $18.00 and you have $15.21.", fix: null,
    });
    expect(sizeStarved({ copies: thin, total: 5 }, { global: false, amount: 0, leverage: 3, cap: 3, equityUsd: 15.21 })?.fix).toBeNull();
  });

  it("is silent when something copies, when the cause is not size, or when they hold nothing", () => {
    const opts = { global: true, amount: null, leverage: 15, cap: 15, equityUsd: 15.21 };
    expect(sizeStarved({ copies: [{ ...book[0], status: "copy", notionalUsd: 40, reason: null }, book[1]], total: 2 }, opts)).toBeNull();
    expect(sizeStarved({ copies: [skipped("BTC", 1, "only_new_positions: their current positions are not copied")], total: 1 }, opts)).toBeNull();
    expect(sizeStarved({ copies: [skipped("BTC", 1, "liquidity cap $8.00 is under the $10.5 minimum"), book[1]], total: 2 }, opts)).not.toBeNull();   // a size reason too
    expect(sizeStarved({ copies: [], total: 0 }, opts)).toBeNull();
    expect(sizeStarved({ copies: [skipped("BTC", 1, "copy $0.04 under the $10.5 minimum", { filtered: true })], total: 1 }, opts)).toBeNull();   // filtered rows do not count
  });
});
