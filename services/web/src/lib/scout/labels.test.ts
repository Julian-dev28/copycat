import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { isApiTooOld } from "./api";
import {
  biasLabel, coattailText, coinLabel, dexHint, FLAG_TEXT, flagText, flagTone, formatHold, isStale, liquidationText, liqTone, netFundingSinceOpen, normalizeOrders,
  refreshCountLabel, refreshEtaLabel, STYLE_META, visibleFlags,
} from "./labels";
import { TRADING_STYLES } from "./types";

describe("labels", () => {
  it("every trading style has a label and a hint", () => {
    for (const s of TRADING_STYLES) {
      expect(STYLE_META[s].label).toBeTruthy();
      expect(STYLE_META[s].hint).toBeTruthy();
    }
  });

  it("every hide_flagged flag has plain-words text", () => {
    for (const f of ["liquidated", "hft", "vault", "inactive"]) expect(FLAG_TEXT[f]).toBeTruthy();
  });

  it("coinLabel splits the HIP-3 dex prefix", () => {
    expect(coinLabel("xyz:TSLA")).toEqual({ name: "TSLA", dex: "xyz" });
    expect(coinLabel("BTC")).toEqual({ name: "BTC", dex: null });
  });

  it("biasLabel thresholds", () => {
    expect(biasLabel(80)).toBe("Strongly long");
    expect(biasLabel(60)).toBe("Leaning long");
    expect(biasLabel(50)).toBe("Balanced");
    expect(biasLabel(40)).toBe("Leaning short");
    expect(biasLabel(20)).toBe("Strongly short");
    expect(biasLabel(null)).toBe("No positions");
  });

  it("liqTone thresholds", () => {
    expect([liqTone(5), liqTone(10), liqTone(25), liqTone(undefined)]).toEqual(["danger", "warn", "ok", "none"]);
  });

  it("netFundingSinceOpen flips HL's paid-positive sign to the app's good-positive convention", () => {
    // Regression, confirmed against real HL data (0x8be0b9c4..., coin INJ, 2026-10-14):
    // clearinghouseState reported cumFunding.sinceOpen = +851.10 for a position whose
    // userFunding rows were all negative (-18, -18, -18, -19: funding PAID every settlement).
    // The Positions tab used to color the raw +851.10 green ("text-up" on >= 0), the exact
    // opposite of what happened to the trader's money.
    expect(netFundingSinceOpen(851.1)).toBe(-851.1);   // paid $851.10: must read negative/red
    expect(netFundingSinceOpen(-18.0)).toBe(18.0);      // received $18: must read positive/green
  });

  it("formatHold", () => {
    expect(formatHold(0.4)).toBe("24m");
    expect(formatHold(0.001)).toBe("1m");
    expect(formatHold(5.5)).toBe("5.5h");
    expect(formatHold(50)).toBe("2.1d");
    expect(formatHold(null)).toBe("—");
  });
});

describe("isStale (spec 4.1: older than 3x the schedule)", () => {
  const H = 3_600_000;
  it("uses next_due - last_ok as the schedule", () => {
    expect(isStale(H, 2 * H, 4 * H)).toBe(false);
    expect(isStale(H, 2 * H, 4 * H + 1)).toBe(true);
  });
  it("unknown schedule is never stale", () => {
    expect(isStale(null, H, 99 * H)).toBe(false);
    expect(isStale(H, null, 99 * H)).toBe(false);
    expect(isStale(H, H, 99 * H)).toBe(false);
  });
});

describe("normalizeOrders", () => {
  it("drops junk and returns newest first", () => {
    expect(normalizeOrders(null)).toEqual([]);
    expect(normalizeOrders([{ coin: 1 }, { coin: "BTC", side: "X" }])).toEqual([]);
  });
});

describe("isApiTooOld", () => {
  it("404, 405 and 503 mean Scout is unavailable; 500 and 401 do not", () => {
    expect(isApiTooOld(new ApiError(404, "x"))).toBe(true);
    expect(isApiTooOld(new ApiError(405, "x"))).toBe(true);
    expect(isApiTooOld(new ApiError(503, "x"))).toBe(true);
    expect(isApiTooOld(new ApiError(500, "x"))).toBe(false);
    expect(isApiTooOld(new ApiError(401, "x"))).toBe(false);
    expect(isApiTooOld(new Error("x"))).toBe(false);
  });
});

describe("flagText (UX audit: raw enum keys never render)", () => {
  // Every flag discovery can emit (services/discovery/README.md + scout/stats.py).
  const API_FLAGS = [
    "vault", "hft", "hft_not_simulated", "too_few_trades", "liquidated", "liquidated:BTC", "non_perp_ignored",
    "max_leverage_unknown:ETH", "candles_partial:SOL", "error:fills_read_failed", "error:sim:ValueError",
    "inactive", "fills_truncated", "stale", "wallet_liquidated", "coattail",
  ];
  it("has words for every api flag, with no snake_case left", () => {
    for (const f of API_FLAGS) {
      const t = flagText(f);
      expect(t, f).toBeTruthy();
      expect(t, f).not.toMatch(/_/);
    }
  });
  it("labels non_perp_ignored in plain words", () => {
    expect(flagText("non_perp_ignored")).toBe(FLAG_TEXT.non_perp_ignored);
    expect(FLAG_TEXT.non_perp_ignored).toMatch(/spot/);
  });
  it("keeps the coin of a prefixed flag and hides error internals", () => {
    expect(flagText("liquidated:BTC")).toBe(`${FLAG_TEXT.liquidated} (BTC)`);
    expect(flagText("error:sim:ValueError")).toBe(FLAG_TEXT.error);
  });
  it("turns an unknown key into words", () => {
    expect(flagText("brand_new_flag")).toBe("brand new flag");
  });
  it("visibleFlags drops fills_truncated and repeats of one key", () => {
    expect(visibleFlags(["liquidated:BTC", "liquidated:ETH", "fills_truncated", "hft"])).toEqual(["liquidated:BTC", "hft"]);
  });
  it("dexHint explains the HIP-3 prefix", () => {
    expect(dexHint("xyz")).toBe("HIP-3 market (xyz deployer)");
  });
  it("flagTone: a scope disclaimer is neutral, not a shouty warning pill (FileHeader regression)", () => {
    expect(flagTone("non_perp_ignored")).toBe("neutral");
    expect(flagTone("candles_partial:SOL")).toBe("neutral");
    expect(flagTone("stale")).toBe("neutral");
  });
  it("flagTone: anything that bears on trusting or copying the trader stays a warning", () => {
    for (const f of ["liquidated", "liquidated:BTC", "wallet_liquidated", "hft", "hft_not_simulated", "vault", "coattail", "too_few_trades", "inactive", "max_leverage_unknown:ETH", "error:sim:ValueError"]) {
      expect(flagTone(f), f).toBe("warning");
    }
  });
  it("flagTone: an unknown flag defaults to warning, not silently neutral", () => {
    expect(flagTone("brand_new_flag")).toBe("warning");
  });
  it("flag texts use they/their, not he/his", () => {
    for (const t of Object.values(FLAG_TEXT)) expect(t).not.toMatch(/\b(he|his|him)\b/i);
  });
});

describe("liquidationText (user_consensus P0 #3: real liquidation, not the sim's)", () => {
  const NOW = Date.UTC(2026, 9, 14);
  const DAY = 86_400_000;
  it("null when the wallet was never really liquidated", () => {
    expect(liquidationText({ liquidations_30d: 0, last_liquidation_ms: null }, NOW)).toBeNull();
  });
  it("plain language with count and recency", () => {
    expect(liquidationText({ liquidations_30d: 2, last_liquidation_ms: NOW - 3 * DAY }, NOW)).toBe("Liquidated 2x in 30d (last: 3d ago)");
    expect(liquidationText({ liquidations_30d: 1, last_liquidation_ms: NOW - DAY }, NOW)).toBe("Liquidated 1x in 30d (last: 1d ago)");
  });
});

describe("coattailText (user_consensus P1 #6)", () => {
  it("null without a leader", () => {
    expect(coattailText({ coattail_leader: null, coattail_share_pct: null })).toBeNull();
  });
  it("names the leader (shortened) and the share", () => {
    const t = coattailText({ coattail_leader: "0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa", coattail_share_pct: 68.4 });
    expect(t).toBe("Opens often land soon after 0x04a9…95aa's (68% of the time)");
  });
  it("drops the share clause when it's missing", () => {
    expect(coattailText({ coattail_leader: "0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa", coattail_share_pct: null }))
      .toBe("Opens often land soon after 0x04a9…95aa's");
  });
});

describe("RefreshBadge progress (indexing tightening: a count, not a bare percent)", () => {
  it("refreshCountLabel is a plain done/total count", () => {
    expect(refreshCountLabel(7, 301)).toBe("7/301");
    expect(refreshCountLabel(0, 301)).toBe("0/301");
    expect(refreshCountLabel(301, 301)).toBe("301/301");
  });

  it("refreshCountLabel never goes negative even on bad input", () => {
    expect(refreshCountLabel(-1, -5)).toBe("0/0");
  });

  it("refreshEtaLabel is null until the server-side gate opens", () => {
    expect(refreshEtaLabel(null)).toBeNull();
    expect(refreshEtaLabel(undefined)).toBeNull();
    expect(refreshEtaLabel(0)).toBe("~1m left");   // 0 is a real estimate (almost done), not "no estimate"
  });

  it("refreshEtaLabel rounds to whole minutes and never shows 0m", () => {
    expect(refreshEtaLabel(30)).toBe("~1m left");     // 30s rounds to 1m, floored, never "0m left"
    expect(refreshEtaLabel(90)).toBe("~2m left");
    expect(refreshEtaLabel(12 * 60)).toBe("~12m left");
    expect(refreshEtaLabel(720)).toBe("~12m left");
  });

  it("refreshEtaLabel rejects non-finite or negative values", () => {
    expect(refreshEtaLabel(NaN)).toBeNull();
    expect(refreshEtaLabel(-5)).toBeNull();
    expect(refreshEtaLabel(Infinity)).toBeNull();
  });
});
