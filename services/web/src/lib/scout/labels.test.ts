import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { isApiTooOld } from "./api";
import { biasLabel, coinLabel, dexHint, FLAG_TEXT, flagText, formatHold, isStale, liqTone, normalizeOrders, STYLE_META, visibleFlags } from "./labels";
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
    "inactive", "fills_truncated", "stale",
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
  it("flag texts use they/their, not he/his", () => {
    for (const t of Object.values(FLAG_TEXT)) expect(t).not.toMatch(/\b(he|his|him)\b/i);
  });
});
