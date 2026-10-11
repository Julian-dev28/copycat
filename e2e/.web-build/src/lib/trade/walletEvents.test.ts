import { describe, expect, it } from "vitest";
import type { EngineEvent } from "@/lib/api/types";
import { eventLine, matchesFilter, mergeEvents, nextBefore, normalizeEvents, pageOf } from "./walletEvents";

const A = "0x" + "a".repeat(40);
const B = "0x" + "b".repeat(40);
const ev = (ts: number, action: EngineEvent["action"], leader = A, extra: Partial<EngineEvent> = {}): EngineEvent => ({ ts_ms: ts, action, leader, coin: "BTC", dry_run: false, ...extra });

describe("events paging", () => {
  it("next before_ms is the oldest ts on a full page, none on a short one", () => {
    expect(nextBefore([ev(30, "open"), ev(10, "add"), ev(20, "skip")], 3)).toBe(10);
    expect(nextBefore([ev(30, "open")], 3)).toBeUndefined();
  });
  it("pageOf: newest first, strictly before the cursor", () => {
    const all = [ev(1, "open"), ev(3, "add"), ev(2, "skip"), ev(4, "close")];
    expect(pageOf(all, 2).map((e) => e.ts_ms)).toEqual([4, 3]);
    expect(pageOf(all, 2, 3).map((e) => e.ts_ms)).toEqual([2, 1]);
  });
  it("merge: live events for this wallet only, deduped, newest first", () => {
    const page = [ev(5, "open"), ev(3, "skip", A, { reason: "paused" })];
    const live = [ev(9, "add"), ev(8, "open", B), ev(5, "open")];
    expect(mergeEvents(live, [page], A).map((e) => e.ts_ms)).toEqual([9, 5, 3]);
    expect(mergeEvents(live, [page], A.toUpperCase().replace("0X", "0x"))).toHaveLength(3);
  });
  it("normalize: list or {events}, junk dropped", () => {
    expect(normalizeEvents([ev(1, "open"), { nope: 1 }])).toHaveLength(1);
    expect(normalizeEvents({ events: [ev(1, "open")] })).toHaveLength(1);
    expect(normalizeEvents(null)).toEqual([]);
  });
  it("lines and filters: every skip carries its reason", () => {
    expect(eventLine(ev(1, "skip", A, { side: "long", reason: "filtered: on Never these coins" }))).toBe("Skipped BTC long: filtered: on Never these coins");
    expect(eventLine(ev(1, "open", A, { side: "short" }))).toBe("Opened BTC short");
    expect(matchesFilter(ev(1, "skip"), "trades")).toBe(false);
    expect(matchesFilter(ev(1, "reduce"), "trades")).toBe(true);
    expect(matchesFilter(ev(1, "skip"), "skips")).toBe(true);
  });
});
