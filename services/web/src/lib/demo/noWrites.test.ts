/**
 * Gate (UX audit #1): with ?demo=1 on the URL, no write reaches the network.
 * 1. Every demo source (Settings, Account, Trade, Scout) is walked: every
 *    method is called and fetch must never see a non-GET request.
 * 2. Every live source's methods are walked too: in demo the api client's
 *    guard must stop each write before fetch, whatever page calls it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoSettingsSource, liveSettingsSource } from "@/components/copy/settingsSource";
import { demoAccounts } from "@/lib/account/demo";
import { liveAccounts } from "@/lib/account/api";
import { demoTrade, liveTrade, resetDemoBooks } from "@/lib/trade/source";
import { demoScout, liveScout } from "@/lib/scout/api";
import { api } from "@/lib/api/client";

const ADDR = "0x" + "ab".repeat(20);
const calls: { url: string; method: string }[] = [];

function jsonOk() {
  return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
}

/** Call every function member with throwaway args; collect settled results (errors are fine, writes are not). */
async function walk(name: string, source: object): Promise<string[]> {
  const called: string[] = [];
  const keys = new Set<string>();
  for (let o: object | null = source; o && o !== Object.prototype; o = Object.getPrototypeOf(o)) {
    for (const k of Object.getOwnPropertyNames(o)) keys.add(k);
  }
  const jobs: Promise<unknown>[] = [];
  for (const k of keys) {
    const fn = (source as Record<string, unknown>)[k];
    if (typeof fn !== "function" || k === "constructor" || k === "walletProvider") continue;
    called.push(`${name}.${k}`);
    const args = [ADDR, { address: ADDR, sim_equity_usd: 1000, top_n: 5, settings_source: "global", allocation_usd: 10, close_positions: false, limit: 5 }, "x"];
    jobs.push(
      Promise.race([
        Promise.resolve().then(() => (fn as (...a: unknown[]) => unknown).apply(source, args)),
        new Promise((r) => setTimeout(r, 1500)),
      ]).catch(() => undefined),
    );
  }
  await Promise.all(jobs);
  return called;
}

const writes = () => calls.filter((c) => !["GET", "HEAD", "OPTIONS"].includes(c.method));

beforeEach(() => {
  calls.length = 0;
  resetDemoBooks();
  window.history.replaceState(null, "", "/settings?demo=1");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: (init?.method ?? "GET").toUpperCase() });
    return jsonOk();
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("demo sources never write to the api", () => {
  it("walks Settings, Account, Trade and Scout demo sources", async () => {
    const trade = demoTrade("default");
    const walked = [
      ...(await walk("settings", demoSettingsSource(trade))),
      ...(await walk("account", demoAccounts)),
      ...(await walk("trade", trade)),
      ...(await walk("scout", demoScout)),
    ];
    expect(walked).toEqual(expect.arrayContaining([
      "settings.patch", "settings.addLeader", "settings.removeLeader",
      "account.transfer", "account.runAction", "trade.copy", "trade.stop", "trade.patch",
    ]));
    expect(calls).toEqual([]);   // demo sources do not even read the api
  }, 15_000);

  it("demo settings writes land in the demo book", async () => {
    const s = demoSettingsSource(demoTrade("default"));
    await s.patch({ dry_run: false, leader_overrides: { [ADDR]: { leverage: 7 } } });
    await s.addLeader(ADDR);
    const after = await s.settings();
    expect(after.dry_run).toBe(false);
    expect(after.leaders).toContain(ADDR);
    expect(after.leader_overrides[ADDR]?.leverage).toBe(7);
    await s.removeLeader(ADDR);
    expect((await s.settings()).leaders).not.toContain(ADDR);
    expect(calls).toEqual([]);
  });
});

describe("live sources in demo mode: the client guard stops every write", () => {
  it("walks the live Settings, Account, Trade and Scout sources and the typed api", async () => {
    await walk("settings", liveSettingsSource);
    await walk("account", liveAccounts);
    await walk("trade", liveTrade);
    await walk("scout", liveScout);
    await walk("api", api);
    expect(writes()).toEqual([]);
    expect(calls.length).toBeGreaterThan(0);   // reads did go out: the walk really ran
  }, 20_000);

  it("outside demo the same walk does send writes (the test can see them)", async () => {
    window.history.replaceState(null, "", "/settings");
    await walk("settings", liveSettingsSource);
    expect(writes().length).toBeGreaterThan(0);
  });
});
