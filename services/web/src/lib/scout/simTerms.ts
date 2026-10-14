/**
 * ScoutSimTerms (contract v16): the Scout board's own copy-sim terms, pure
 * helpers shared by the toolbar control (BoardControls.tsx) and the page
 * note (app/scout/page.tsx). No fetching here; see hooks/useScout.ts for
 * useScoutSimTerms/useSetScoutSimTerms and lib/scout/api.ts for the source.
 *
 * The toolbar collapses two contract fields (exposure_mode + leverage_mode)
 * into one choice, because that is the only distinction a trader cares about
 * here: copy at THEIR leverage (capped), or at a FIXED leverage you pick.
 * `leverage` doubles as the cap in "their" mode and the fixed value in
 * "fixed" mode (see contracts/models.py ScoutSimTerms.to_settings).
 */
import { formatUsd } from "@/lib/format";
import type { ScoutSimTerms } from "./types";

export type LeverageChoice = "their" | "fixed";

export function leverageChoiceOf(terms: Pick<ScoutSimTerms, "exposure_mode">): LeverageChoice {
  return terms.exposure_mode === "target" ? "fixed" : "their";
}

/** The patch to apply when the user picks a leverage choice + Nx in the drawer. */
export function leveragePatch(choice: LeverageChoice, n: number): Pick<ScoutSimTerms, "exposure_mode" | "leverage_mode" | "leverage" | "target_leverage"> {
  return choice === "fixed"
    ? { exposure_mode: "target", leverage_mode: "fixed", leverage: n, target_leverage: n }
    : { exposure_mode: "match", leverage_mode: "match", leverage: n, target_leverage: n };
}

/** The leverage number the drawer shows, whichever choice is active. */
export function leverageN(terms: Pick<ScoutSimTerms, "exposure_mode" | "leverage" | "target_leverage">): number {
  return terms.exposure_mode === "target" ? terms.target_leverage : terms.leverage;
}

/**
 * The Scout page note, in the ACTUAL terms (never the operator's raw
 * numbers out of context): "Ranked by what copying each wallet with $100 at
 * 3x leverage would have earned a $1K account over 30 days." (the default;
 * "their leverage (Nx cap)" when the choice is "their").
 */
export function simTermsNote(terms: ScoutSimTerms): string {
  if (terms.use_live_settings) {
    return "Ranked by what copying each wallet at your own trading settings would have earned you over the last 30 days.";
  }
  const lev = leverageChoiceOf(terms) === "fixed" ? `${terms.target_leverage}x leverage` : `their leverage (${terms.leverage}x cap)`;
  return `Ranked by what copying each wallet with ${formatUsd(terms.allocation_usd, true)} at ${lev} would have earned a ${formatUsd(terms.sim_equity_usd, true)} account over 30 days.`;
}

/** "re-ranking at new terms, n of total simmed" while a terms-driven resim runs. */
export function reRankingNote(done: number, total: number): string {
  return `Ranking at your new terms: ${done} of ${total} wallets simmed so far. Scores below are still from the previous terms until this finishes.`;
}
