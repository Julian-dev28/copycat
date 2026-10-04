import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { fixtureRows } from "@/lib/scout/fixtures";
import { apiProblem, legacyRedirect, problemText } from "./apiState";
import { normalizeApiPreview, mergePreview } from "./apiPreview";
import { demoSettings, demoStatus } from "./fixtures";
import { buildMarkets, roePct, TOP_N, walletsFromStatus, walletState } from "./markets";
import { localPreview } from "./preview";

const NOW = 1_760_000_000_000;
const rows = fixtureRows(NOW);

describe("markets list", () => {
  it("top: at most 25, flagged wallets dropped", () => {
    const top = buildMarkets(rows, [], "top", "");
    expect(top.length).toBeLessThanOrEqual(TOP_N);
    expect(top.some((m) => m.row?.flags.includes("liquidated"))).toBe(false);
  });

  it("mine: every book wallet, with a stub when the board doesn't have it", () => {
    const stranger = "0x" + "1".repeat(40);
    const mine = buildMarkets(rows, [rows[0].address, stranger], "mine", "");
    expect(mine.map((m) => m.address)).toEqual([rows[0].address, stranger]);
    expect(mine[1].row).toBeNull();
    expect(mine.every((m) => m.inBook)).toBe(true);
  });

  it("search by name or address; a full unknown address becomes a selectable row", () => {
    expect(buildMarkets(rows, [], "all", rows[3].address.slice(2, 10)).map((m) => m.address)).toContain(rows[3].address);
    const unknown = "0x" + "2".repeat(40);
    expect(buildMarkets(rows, [], "all", unknown.toUpperCase().replace("0X", "0x"))[0].address).toBe(unknown);
  });
});

describe("your wallets", () => {
  const base = { stopping: false, read_ok: true };
  it("status precedence: stopping > paused > can't read > dry run > active", () => {
    expect(walletState({ ...base, stopping: true }, { enabled: false, dry_run: true })).toBe("stopping");
    expect(walletState(base, { enabled: false, dry_run: false })).toBe("paused");
    expect(walletState({ ...base, read_ok: false }, { enabled: true, dry_run: false })).toBe("no_read");
    expect(walletState(base, { enabled: true, dry_run: true })).toBe("dry_run");
    expect(walletState(base, { enabled: true, dry_run: false })).toBe("active");
  });

  it("ROE = (uPnL + realized - fees) / invested when the api doesn't send it", () => {
    expect(roePct({ roe_pct: null, allocation_usd: 100, unrealized_pnl_usd: 5, realized_pnl_usd: 2, fees_usd: 1 })).toBeCloseTo(6);
    expect(roePct({ roe_pct: 3, allocation_usd: 100, unrealized_pnl_usd: 5, realized_pnl_usd: 2, fees_usd: 1 })).toBe(3);
  });

  it("fallback rows from /api/status + settings for an api without /api/wallets", () => {
    const s = demoSettings();
    const a = rows[0].address;
    s.leaders = [a, rows[1].address];
    s.leader_overrides[a] = { allocation_usd: 50, exposure_mode: "target", target_leverage: 10 };
    const { status } = demoStatus(s, "default", NOW, new Set());
    const w = walletsFromStatus(status, s);
    expect(w).toHaveLength(1); // the second leader has no allocation: not "invested"
    expect(w[0]).toMatchObject({ address: a, allocation_usd: 50, exposure_mode: "target" });
    expect(w[0].exposure_usd).toBeGreaterThan(0);
  });
});

describe("api problems and routes", () => {
  it("classifies status codes", () => {
    expect(apiProblem(new ApiError(404, "Not Found"))).toBe("too_old");
    expect(apiProblem(new ApiError(503, "x"))).toBe("unavailable");
    expect(apiProblem(new ApiError(401, "x"))).toBe("unauthorized");
    expect(apiProblem(new ApiError(0, "x"))).toBe("unreachable");
    expect(apiProblem(new ApiError(422, "bad"))).toBe("rejected");
    expect(apiProblem(null)).toBeNull();
    expect(problemText(new ApiError(404, "Not Found"), "wallet copy")).toMatch(/no wallet copy route/);
  });

  it("legacy routes redirect and keep the query", () => {
    expect(legacyRedirect("/copy")).toBe("/settings");
    expect(legacyRedirect("/positions", { demo: "1" })).toBe("/portfolio?demo=1");
    expect(legacyRedirect("/trade", { w: "0xabc", demo: "1" })).toBe("/?w=0xabc&demo=1");
  });
});

describe("api preview normalization", () => {
  it("maps wire fields and fills blanks from the local estimate", () => {
    const api = normalizeApiPreview({
      copies: [
        { coin: "BTC", side: "long", notional_usd: 300, leverage: 10, status: "copy", cycles: 3 },
        { coin: "kPEPE", side: "long", notional_usd: 0, leverage: 10, status: "skipped", reason: "below $10 min" },
      ],
      exposure_usd: 300,
    });
    expect(api.copied).toBe(1);
    expect(api.copies[1].status).toBe("skipped");
    expect(api.liquidityCapped).toBe(true);
    const local = localPreview({
      allocationUsd: 30, mode: "target", targetLeverage: 10, marginMode: "isolated", smallMode: "skip", leaderEquityUsd: 1,
      positions: [{ coin: "BTC", side: "long", notional_usd: 1, leverage: 1 }],
    });
    const m = mergePreview(api, local);
    expect(m.targetExposureUsd).toBe(300);
    expect(m.liq.kind).toBe("isolated");
    expect(m.source).toBe("api");
  });

  it("garbage in: an empty preview, not a crash", () => {
    expect(normalizeApiPreview("nope").copies).toEqual([]);
  });
});
