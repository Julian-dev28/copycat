import { describe, expect, it } from "vitest";
import { DEFAULT_SIM_TERMS } from "./fixtures";
import { leverageChoiceOf, leverageN, leveragePatch, reRankingNote, simTermsNote } from "./simTerms";
import type { ScoutSimTerms } from "./types";

describe("leverageChoiceOf / leverageN / leveragePatch", () => {
  it("'their leverage' is exposure_mode match, 'fixed' is target", () => {
    expect(leverageChoiceOf({ exposure_mode: "match" })).toBe("their");
    expect(leverageChoiceOf({ exposure_mode: "target" })).toBe("fixed");
  });

  it("leverageN reads target_leverage in fixed mode, leverage in their mode", () => {
    expect(leverageN({ exposure_mode: "target", leverage: 3, target_leverage: 7 })).toBe(7);
    expect(leverageN({ exposure_mode: "match", leverage: 3, target_leverage: 7 })).toBe(3);
  });

  it("leveragePatch('fixed', n) sets exposure_mode target + leverage_mode fixed, both leverage fields to n", () => {
    expect(leveragePatch("fixed", 8)).toEqual({
      exposure_mode: "target", leverage_mode: "fixed", leverage: 8, target_leverage: 8,
    });
  });

  it("leveragePatch('their', n) sets exposure_mode match + leverage_mode match, both leverage fields to n", () => {
    expect(leveragePatch("their", 12)).toEqual({
      exposure_mode: "match", leverage_mode: "match", leverage: 12, target_leverage: 12,
    });
  });

  it("round-trips through leverageChoiceOf/leverageN: patch then read back gives the same choice and number", () => {
    for (const [choice, n] of [["fixed", 5], ["their", 9]] as const) {
      const patch = leveragePatch(choice, n);
      expect(leverageChoiceOf(patch)).toBe(choice);
      expect(leverageN(patch)).toBe(n);
    }
  });
});

describe("simTermsNote", () => {
  // formatUsd's compact notation (lib/format.ts, shared with every other $ amount in the app,
  // e.g. TraderCard's account value) always shows one decimal: "$100.0", "$1.0K", never "$100"/"$1K".
  it("default terms: fixed 3x, $100 allocation, $1K account (measured, scout/README.md)", () => {
    expect(simTermsNote(DEFAULT_SIM_TERMS)).toBe(
      "Ranked by what copying each wallet with $100.0 at 3x leverage would have earned a $1.0K account over 30 days.",
    );
  });

  it("'their leverage' choice reads '(Nx cap)'", () => {
    const terms: ScoutSimTerms = { ...DEFAULT_SIM_TERMS, exposure_mode: "match", leverage_mode: "match", leverage: 10 };
    expect(simTermsNote(terms)).toBe(
      "Ranked by what copying each wallet with $100.0 at their leverage (10x cap) would have earned a $1.0K account over 30 days.",
    );
  });

  it("use_live_settings overrides every other field in the wording", () => {
    const terms: ScoutSimTerms = { ...DEFAULT_SIM_TERMS, use_live_settings: true, allocation_usd: 99_999 };
    expect(simTermsNote(terms)).toBe(
      "Ranked by what copying each wallet at your own trading settings would have earned you over the last 30 days.",
    );
  });

  it("formats the equity and allocation with formatUsd's compact notation", () => {
    const terms: ScoutSimTerms = { ...DEFAULT_SIM_TERMS, allocation_usd: 500, sim_equity_usd: 5_000, leverage: 25, target_leverage: 25 };
    expect(simTermsNote(terms)).toBe(
      "Ranked by what copying each wallet with $500.0 at 25x leverage would have earned a $5.0K account over 30 days.",
    );
  });
});

describe("reRankingNote", () => {
  it("names done/total and says scores are still from the previous terms", () => {
    expect(reRankingNote(42, 301)).toBe(
      "Ranking at your new terms: 42 of 301 wallets simmed so far. Scores below are still from the previous terms until this finishes.",
    );
  });
});
