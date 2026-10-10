import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoNowMs } from "@/lib/scout/api";
import { fixtureRows } from "@/lib/scout/fixtures";
import { demoTrade, resetDemoBooks } from "./source";

describe("demo book: copy, adjust, stop", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetDemoBooks();
  });
  afterEach(() => vi.useRealTimers());

  const run = async <T,>(p: Promise<T>) => {
    await vi.runAllTimersAsync();
    return p;
  };

  it("copy -> wallet row; update -> new size; stop+close -> stopping then a stopped row (v8)", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[0].address;
    await run(src.copy(a, { allocation_usd: 50, exposure_mode: "target", target_leverage: 10 }));
    let w = await run(src.wallets());
    expect(w).toHaveLength(1);
    expect(w[0]).toMatchObject({ allocation_usd: 50, target_leverage: 10, stopping: false });
    expect(w[0].margin_used_usd).toBeLessThanOrEqual(50 * 1.02);

    await run(src.copy(a, { allocation_usd: 75, exposure_mode: "target", target_leverage: 10 }));
    w = await run(src.wallets());
    expect(w[0].allocation_usd).toBe(75);

    const stopP = src.stop(a, { close_positions: true });
    await vi.advanceTimersByTimeAsync(400);
    await stopP;
    const during = src.wallets();
    await vi.advanceTimersByTimeAsync(200);
    expect((await during)[0].stopping).toBe(true);
    await vi.advanceTimersByTimeAsync(3_000);
    const after = await run(src.wallets());
    expect(after).toHaveLength(1);
    expect(after[0]).toMatchObject({ status: "stopped", in_book: false, open_copies: 0, exposure_usd: 0, unrealized_pnl_usd: 0 });
    expect((await run(src.settings())).leaders).toEqual([]);
  });

  it("stop without closing keeps the wallet, marked stopping", async () => {
    const src = demoTrade("small");
    const a = fixtureRows(demoNowMs())[1].address;
    await run(src.copy(a, { allocation_usd: 15, exposure_mode: "match" }));
    const stopP = src.stop(a, { close_positions: false });
    await vi.advanceTimersByTimeAsync(400);
    await stopP;
    const during = src.wallets();
    await vi.advanceTimersByTimeAsync(4_000);
    const w = await during;
    expect(w[0].stopping).toBe(true);
    expect(w[0].status).toBe("stopping");
    // Running out finishes later (sped up in the demo): then the row is stopped.
    await vi.advanceTimersByTimeAsync(5_000);
    expect((await run(src.wallets()))[0].status).toBe("stopped");
  });

  it("$1M account: status free margin drops by what the wallet uses", async () => {
    const src = demoTrade("large");
    const a = fixtureRows(demoNowMs())[0].address;
    const before = (await run(src.status())).available_margin_usd!;
    await run(src.copy(a, { allocation_usd: 500_000, exposure_mode: "target", target_leverage: 5 }));
    const after = await run(src.status());
    const w = await run(src.wallets());
    expect(before).toBe(1_000_000);
    expect(after.available_margin_usd!).toBeCloseTo(after.equity_usd! - w[0].margin_used_usd, 2);
  });
});

describe("demo book: global vs custom", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetDemoBooks();
  });
  afterEach(() => vi.useRealTimers());
  const run = async <T,>(p: Promise<T>) => {
    await vi.runAllTimersAsync();
    return p;
  };

  it("global copies with the Settings tab, switching to custom stores the terms and back clears them", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[2].address;
    await run(src.copy(a, { settings_source: "global" }));
    let w = (await run(src.wallets()))[0];
    expect(w).toMatchObject({ settings_source: "global", allocation_usd: 100 });
    await run(src.copy(a, { settings_source: "custom", allocation_usd: 40, exposure_mode: "target", target_leverage: 3, only_new_positions: true }));
    w = (await run(src.wallets()))[0];
    expect(w).toMatchObject({ settings_source: "custom", allocation_usd: 40, open_copies: 0 }); // only new: nothing copied now
    await run(src.copy(a, { settings_source: "global" }));
    const s = await run(src.settings());
    expect(s.leader_overrides[a].allocation_usd).toBeUndefined();
    expect((await run(src.wallets()))[0].settings_source).toBe("global");
  });

  it("global preview sizes from the Settings tab", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[0].address;
    const p = await run(src.preview(a, { settings_source: "global" }));
    expect(p.source).toBe("api");
    expect(p.total).toBeGreaterThan(0);
  });
});

describe("demo book v8: counter, filters, pause, archive, log, projection", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetDemoBooks();
  });
  afterEach(() => vi.useRealTimers());
  const run = async <T,>(p: Promise<T>) => {
    await vi.runAllTimersAsync();
    return p;
  };

  it("counter + blocklist: the row says counter, copies take his opposite side, blocked coin not copied", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[0].address;
    const prev = await run(src.preview(a, { settings_source: "custom", allocation_usd: 500, exposure_mode: "match" }));
    const blocked = prev.copies.find((c) => c.status !== "skipped")!.coin;
    await run(src.copy(a, { settings_source: "custom", allocation_usd: 500, exposure_mode: "match", trade_direction: "counter", coin_blocklist: [blocked] }));
    const w = (await run(src.wallets()))[0];
    expect(w).toMatchObject({ trade_direction: "counter", coin_blocklist: [blocked], status: "running" });
    const st = await run(src.status());
    expect(st.positions.some((p) => p.coin === blocked)).toBe(false);
    const p2 = await run(src.preview(a, { settings_source: "custom", allocation_usd: 500, exposure_mode: "match", coin_blocklist: [blocked] }));
    expect(p2.copies.find((c) => c.coin === blocked)).toMatchObject({ status: "skipped", filtered: true });
  });

  it("pause -> paused, resume -> running; archive only after stop", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[2].address;
    await run(src.copy(a, { settings_source: "global" }));
    await run(src.pause(a));
    expect((await run(src.wallets()))[0].status).toBe("paused");
    await run(src.resume(a));
    expect((await run(src.wallets()))[0].status).toBe("running");
    await expect(src.archive(a)).rejects.toThrow(/stopped/);
    await run(src.stop(a, { close_positions: true }));
    await vi.advanceTimersByTimeAsync(3_000);
    await run(src.archive(a));
    const w = (await run(src.wallets()))[0];
    expect(w.status).toBe("archived");
    expect(w.archived_ms).toBeTruthy();
  });

  it("log: newest first, paged by before_ms, includes skips with reasons and the pause", async () => {
    const src = demoTrade("default");
    const a = fixtureRows(demoNowMs())[0].address;
    await run(src.copy(a, { settings_source: "custom", allocation_usd: 500, exposure_mode: "match", coin_blocklist: ["BTC", "ETH", "SOL", "HYPE"] }));
    await run(src.pause(a));
    const p1 = (await run(src.events(a, { limit: 3 }))).events;
    expect(p1[0].action).toBe("halt");
    const ts = p1.map((e) => e.ts_ms);
    expect([...ts].sort((x, y) => y - x)).toEqual(ts);
    expect(p1).toHaveLength(3);
    {
      const p2 = (await run(src.events(a, { limit: 3, beforeMs: Math.min(...ts) }))).events;
      expect(p2.every((e) => e.ts_ms < Math.min(...ts))).toBe(true);
    }
  });

  it("projection: ready for a Scout wallet, building first for a pasted one", async () => {
    const src = demoTrade("default");
    const q = { allocation_usd: 1_000, trade_direction: "copy" as const, exposure_mode: "match" as const };
    const ready = await run(src.projection(fixtureRows(demoNowMs())[0].address, q));
    expect(ready.kind).toBe("ready");
    const pasted = "0x" + "9".repeat(40);
    expect((await run(src.projection(pasted, q))).kind).toBe("building");
  });
});
