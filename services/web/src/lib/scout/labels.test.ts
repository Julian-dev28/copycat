import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { isApiTooOld } from "./api";
import { biasLabel, coinLabel, FLAG_TEXT, formatHold, isStale, liqTone, normalizeOrders, STYLE_META } from "./labels";
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
