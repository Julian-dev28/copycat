/**
 * ?demo=1 sim terms: in memory (sessionStorage-backed), no network. GET
 * starts at the documented default; PUT re-sorts the board at once
 * (lib/scout/fixtures.ts::applySimTerms), exactly what the e2e demo lane
 * (e2e/tests/demo/scout.spec.ts) drives through the UI.
 */
import { afterEach, describe, expect, it } from "vitest";
import { demoScout, resetDemoSimTerms } from "./api";
import { DEFAULT_SIM_TERMS } from "./fixtures";
import { boardStateToApiQuery, DEFAULT_BOARD } from "./query";

const ALL_Q = boardStateToApiQuery({ ...DEFAULT_BOARD, limit: 200 });

afterEach(() => resetDemoSimTerms());

describe("demoScout sim terms", () => {
  it("starts at the documented default", async () => {
    expect(await demoScout.simTerms()).toEqual(DEFAULT_SIM_TERMS);
  });

  it("PUT stores the new terms and GET reflects them", async () => {
    const next = { ...DEFAULT_SIM_TERMS, allocation_usd: 500, sim_equity_usd: 5_000 };
    const saved = await demoScout.putSimTerms(next);
    expect(saved).toEqual(next);
    expect(await demoScout.simTerms()).toEqual(next);
  });

  it("a PUT re-sorts the board (applySimTerms), without any network call", async () => {
    const before = (await demoScout.traders(ALL_Q)).rows.map((r) => r.address);
    await demoScout.putSimTerms({ ...DEFAULT_SIM_TERMS, leverage: 25, target_leverage: 25, allocation_usd: 500 });
    const after = (await demoScout.traders(ALL_Q)).rows.map((r) => r.address);
    expect(after).not.toEqual(before);
  });

  it("resetDemoSimTerms() forgets the session's choice", async () => {
    await demoScout.putSimTerms({ ...DEFAULT_SIM_TERMS, allocation_usd: 999 });
    expect((await demoScout.simTerms()).allocation_usd).toBe(999);
    resetDemoSimTerms();
    expect(await demoScout.simTerms()).toEqual(DEFAULT_SIM_TERMS);
  });
});
