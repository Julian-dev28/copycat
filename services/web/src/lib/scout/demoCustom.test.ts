/**
 * ?demo=1 custom wallets: in memory, no network. The demo source must behave
 * like the api after its build: the row is on the board with custom=true,
 * preset=custom and the Custom count see it, the file opens, and removal
 * takes it off at once.
 */
import { afterEach, describe, expect, it } from "vitest";
import { demoNowMs, demoScout, resetDemoCustom } from "./api";
import { fixtureRows } from "./fixtures";
import { boardStateToApiQuery, DEFAULT_BOARD } from "./query";

const NEW = "0x" + "77".repeat(20);
const CUSTOM_Q = boardStateToApiQuery({ ...DEFAULT_BOARD, preset: "custom", limit: 200 });
const ALL_Q = boardStateToApiQuery({ ...DEFAULT_BOARD, limit: 200 });

afterEach(() => resetDemoCustom());

describe("demoScout custom wallets", () => {
  it("starts empty", async () => {
    expect(await demoScout.customList()).toEqual([]);
    expect((await demoScout.traders(CUSTOM_Q)).total).toBe(0);
    expect((await demoScout.presets()).custom).toBe(0);
  });

  it("an unknown address gets a row on the board, in the custom preset, with a file", async () => {
    const before = (await demoScout.traders(ALL_Q)).total;
    const added = await demoScout.customAdd(NEW.toUpperCase().replace("0X", "0x"));
    expect(added).toMatchObject({ address: NEW, on_board: true, queued: false });
    const custom = await demoScout.traders(CUSTOM_Q);
    expect(custom.total).toBe(1);
    expect(custom.rows[0]).toMatchObject({ address: NEW, custom: true, display_name: null });
    expect((await demoScout.traders(ALL_Q)).total).toBe(before + 1);
    expect((await demoScout.presets()).custom).toBe(1);
    expect((await demoScout.customList()).map((c) => c.address)).toEqual([NEW]);
    const file = await demoScout.profile(NEW);
    expect(file.kind).toBe("ready");
    if (file.kind === "ready") expect(file.profile.row.address).toBe(NEW);
    // idempotent
    await demoScout.customAdd(NEW);
    expect((await demoScout.traders(CUSTOM_Q)).total).toBe(1);
  });

  it("a wallet already on the board is marked custom, not duplicated", async () => {
    const top = fixtureRows(demoNowMs())[2].address;
    const before = (await demoScout.traders(ALL_Q)).total;
    await demoScout.customAdd(top);
    const all = await demoScout.traders(ALL_Q);
    expect(all.total).toBe(before);
    expect(all.rows.filter((r) => r.address === top)).toHaveLength(1);
    expect(all.rows.find((r) => r.address === top)?.custom).toBe(true);
    expect((await demoScout.traders(CUSTOM_Q)).rows.map((r) => r.address)).toEqual([top]);
  });

  it("remove takes it off the board and out of the count at once", async () => {
    await demoScout.customAdd(NEW);
    await demoScout.customRemove(NEW);
    expect((await demoScout.traders(CUSTOM_Q)).total).toBe(0);
    expect((await demoScout.traders(ALL_Q)).rows.some((r) => r.address === NEW)).toBe(false);
    expect((await demoScout.presets()).custom).toBe(0);
    expect(await demoScout.customList()).toEqual([]);
  });
});
