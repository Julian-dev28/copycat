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

  it("copy -> wallet row; update -> new size; stop+close -> stopping then gone", async () => {
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
    expect(await run(src.wallets())).toEqual([]);
    expect((await run(src.settings())).leaders).toEqual([]);
  });

  it("stop without closing keeps the wallet, marked stopping", async () => {
    const src = demoTrade("small");
    const a = fixtureRows(demoNowMs())[1].address;
    await run(src.copy(a, { allocation_usd: 15, exposure_mode: "match" }));
    await run(src.stop(a, { close_positions: false }));
    await vi.advanceTimersByTimeAsync(5_000);
    const w = await run(src.wallets());
    expect(w[0].stopping).toBe(true);
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
