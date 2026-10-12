import { describe, expect, it } from "vitest";
import { fixtureRows } from "./fixtures";
import {
  activeFilterChips, applyBoardQuery, boardStateToApiQuery, boardStateToSearch, clearFilters, countActiveFilters, DEFAULT_BOARD, MAX_LIMIT,
  normalizePresets, parseAmount, parseBoardState,
} from "./query";

const NOW = Date.UTC(2026, 9, 4, 12);
const parse = (qs: string) => parseBoardState(new URLSearchParams(qs));

describe("parseBoardState", () => {
  it("empty URL is the default board", () => {
    expect(parse("")).toEqual(DEFAULT_BOARD);
  });

  it("drops malformed values instead of throwing", () => {
    const s = parse("window=2y&sort=bogus&order=up&preset=coin:$$$&style=nope&coin=BTC&coin=BTC&coin=<x>&min_av=abc&view=grid");
    expect(s.window).toBe("30d");
    expect(s.sort).toBe("fit");
    expect(s.order).toBe("desc");
    expect(s.preset).toBe("all");
    expect(s.styles).toEqual([]);
    expect(s.coins).toEqual(["BTC"]);
    expect(s.minAv).toBeNull();
    expect(s.view).toBe("cards");
  });

  it("clamps and orders the Copy Fit range, clamps limit", () => {
    const s = parse("min_fit=150&max_fit=-4&limit=9999");
    expect([s.minFit, s.maxFit]).toEqual([0, 100]);
    const t = parse("min_fit=80&max_fit=20");
    expect([t.minFit, t.maxFit]).toEqual([20, 80]);
    expect(s.limit).toBe(MAX_LIMIT);
  });

  it("accepts HIP-3 coin presets and search text", () => {
    const s = parse("preset=coin:xyz:TSLA&q=%200xAbC%20&unit=pct&view=table&hide_flagged=1");
    expect(s.preset).toBe("coin:xyz:TSLA");
    expect(s.q).toBe("0xAbC");
    expect(s.unit).toBe("pct");
    expect(s.view).toBe("table");
    expect(s.hideFlagged).toBe(true);
  });
});

describe("boardStateToApiQuery / boardStateToSearch", () => {
  it("api query always carries window, sort, order, preset, limit, offset (stable cache key)", () => {
    expect(boardStateToApiQuery(DEFAULT_BOARD)).toBe("window=30d&sort=fit&order=desc&preset=all&limit=60&offset=0");
  });

  it("maps every filter to the spec section 5 param names, UI-only fields never sent", () => {
    const s = {
      ...DEFAULT_BOARD, window: "7d" as const, coins: ["BTC", "xyz:TSLA"], minAv: 10_000, maxAv: 1e6, minPnl: -5, maxPnl: 5e5,
      styles: ["swing" as const], minFit: 40, maxFit: 90, maxDd: 25, minTrips: 10, activeWithinH: 168, hideFlagged: true,
      q: "0xab", unit: "pct" as const, view: "table" as const,
    };
    const p = new URLSearchParams(boardStateToApiQuery(s));
    expect(p.getAll("coin")).toEqual(["BTC", "xyz:TSLA"]);
    expect(p.get("min_av")).toBe("10000");
    expect(p.get("max_av")).toBe("1000000");
    expect(p.get("min_pnl")).toBe("-5");
    expect(p.get("style")).toBe("swing");
    expect(p.get("min_fit")).toBe("40");
    expect(p.get("max_fit")).toBe("90");
    expect(p.get("max_dd")).toBe("25");
    expect(p.get("min_trips")).toBe("10");
    expect(p.get("active_within_h")).toBe("168");
    expect(p.get("hide_flagged")).toBe("true");
    expect(p.get("q")).toBe("0xab");
    expect(p.has("unit")).toBe(false);
    expect(p.has("view")).toBe(false);
  });

  it("clean board has a clean URL; demo flag is kept", () => {
    expect(boardStateToSearch(DEFAULT_BOARD)).toBe("");
    expect(boardStateToSearch(DEFAULT_BOARD, { demo: "1" })).toBe("demo=1");
  });

  it("URL round-trips", () => {
    const s = { ...DEFAULT_BOARD, window: "1d" as const, sort: "roi" as const, preset: "hip3", styles: ["scalp" as const], minFit: 30, unit: "pct" as const, view: "table" as const, limit: 120 };
    expect(parse(boardStateToSearch(s))).toEqual(s);
  });
});

describe("filter count and clear", () => {
  it("counts filters, not window/sort/preset", () => {
    expect(countActiveFilters({ ...DEFAULT_BOARD, window: "7d", preset: "hip3" })).toBe(0);
    expect(countActiveFilters({ ...DEFAULT_BOARD, minAv: 1, maxAv: 2, minFit: 10, q: "x" })).toBe(3);
  });

  it("clearFilters keeps window, sort, preset, unit, view", () => {
    const s = { ...DEFAULT_BOARD, window: "7d" as const, preset: "hip3", unit: "pct" as const, minAv: 5, styles: ["swing" as const] };
    const c = clearFilters(s);
    expect(countActiveFilters(c)).toBe(0);
    expect([c.window, c.preset, c.unit]).toEqual(["7d", "hip3", "pct"]);
  });
});

describe("parseAmount", () => {
  it("reads human amounts", () => {
    expect(parseAmount("10k")).toBe(10_000);
    expect(parseAmount("$1.5M")).toBe(1_500_000);
    expect(parseAmount("1,000")).toBe(1000);
    expect(parseAmount("-5k")).toBe(-5000);
    expect(parseAmount(" ")).toBeNull();
    expect(parseAmount("ten")).toBeUndefined();
  });
});

describe("normalizePresets", () => {
  it("reads the contract shape", () => {
    expect(normalizePresets({ coins: ["BTC", "xyz:TSLA"], coin_counts: { BTC: 40 }, hip3_count: 12, total: 280 })).toEqual({
      coins: [{ coin: "BTC", traders: 40 }, { coin: "xyz:TSLA", traders: 0 }], hip3: 12, total: 280,
    });
  });

  it("reads the draft shape and degrades on junk", () => {
    expect(normalizePresets({ coins: [{ coin: "ETH", traders: 3 }, { coin: "bad coin!" }], hip3: 2 }).coins).toEqual([{ coin: "ETH", traders: 3 }]);
    expect(normalizePresets(null)).toEqual({ coins: [], hip3: 0, total: 0 });
    expect(normalizePresets({ coins: "BTC", hip3_count: -1 })).toEqual({ coins: [], hip3: 0, total: 0 });
  });
});

describe("applyBoardQuery (demo mirror of the server)", () => {
  const rows = fixtureRows(NOW);

  it("default sort is Copy Fit desc, total counts every match", () => {
    const { rows: out, total } = applyBoardQuery(rows, DEFAULT_BOARD, NOW);
    expect(total).toBe(rows.length);
    const fits = out.map((r) => r.score.copy_fit?.value ?? -1);
    expect(fits).toEqual([...fits].sort((a, b) => b - a));
  });

  it("filters by Copy Fit range and account value", () => {
    const { rows: out } = applyBoardQuery(rows, { ...DEFAULT_BOARD, minFit: 50, minAv: 50_000 }, NOW);
    for (const r of out) {
      expect(r.score.copy_fit?.value ?? 0).toBeGreaterThanOrEqual(50);
      expect(r.account_value_usd).toBeGreaterThanOrEqual(50_000);
    }
  });

  it("coin preset keeps traders whose #1 coin matches", () => {
    const coin = rows[0].top_coins[0]?.coin;
    expect(coin).toBeTruthy();
    const { rows: out } = applyBoardQuery(rows, { ...DEFAULT_BOARD, preset: `coin:${coin}` }, NOW);
    expect(out.length).toBeGreaterThan(0);
    for (const r of out) expect(r.top_coins[0].coin).toBe(coin);
  });

  it("address prefix search is case-insensitive", () => {
    const target = rows[3].address;
    const { rows: out } = applyBoardQuery(rows, { ...DEFAULT_BOARD, q: target.slice(0, 10).toUpperCase().replace("0X", "0x") }, NOW);
    expect(out.map((r) => r.address)).toContain(target);
  });

  it("limit caps the page, not the total", () => {
    const { rows: out, total } = applyBoardQuery(rows, { ...DEFAULT_BOARD, limit: 5 }, NOW);
    expect(out).toHaveLength(5);
    expect(total).toBe(rows.length);
  });
});

describe("activeFilterChips", () => {
  const busy = {
    ...DEFAULT_BOARD, minAv: 10_000, maxPnl: 2_500_000, styles: ["swing" as const, "position" as const], minFit: 60, maxDd: 20,
    minTrips: 5, activeWithinH: 72, hideFlagged: true, coins: ["BTC"], q: "whale",
  };

  it("one chip per counted filter, so the badge and the chips agree", () => {
    expect(activeFilterChips(busy)).toHaveLength(countActiveFilters(busy));
    expect(activeFilterChips(DEFAULT_BOARD)).toEqual([]);
  });

  it("each chip's patch clears exactly its own filter", () => {
    for (const chip of activeFilterChips(busy)) {
      const next = { ...busy, ...chip.clear };
      expect(countActiveFilters(next), chip.key).toBe(countActiveFilters(busy) - 1);
    }
  });

  it("reads in words", () => {
    const labels = activeFilterChips(busy, (st) => st.toUpperCase()).map((c) => c.label);
    expect(labels).toContain("Account at least $10k");
    expect(labels).toContain("PnL at most $2.5M");
    expect(labels).toContain("SWING, POSITION");
    expect(labels).toContain("Active in 3d");
  });
});
