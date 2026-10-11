import { describe, expect, it } from "vitest";
import { archiveConfirmed, inTab, rowActions, tabCounts, tabOf, walletStatus } from "./lifecycle";
import type { WalletPosition } from "./types";

const base: WalletPosition = {
  address: "0x" + "1".repeat(40), read_ok: true, open_copies: 2, margin_used_usd: 10, exposure_usd: 50, unrealized_pnl_usd: 1,
  realized_pnl_usd: 0, fees_usd: 0, stopping: false,
};
const w = (p: Partial<WalletPosition>) => ({ ...base, ...p });

describe("lifecycle actions per status", () => {
  it("running: pause, adjust, stop; paused: resume instead of pause", () => {
    expect(rowActions("running")).toEqual(["pause", "adjust", "stop", "log", "share"]);
    expect(rowActions("paused")).toEqual(["resume", "adjust", "stop", "log", "share"]);
  });
  it("archive only for stopped; stopping and archived are read-only", () => {
    expect(rowActions("stopped")).toContain("archive");
    for (const s of ["running", "paused", "stopping", "archived"] as const) expect(rowActions(s)).not.toContain("archive");
    expect(rowActions("stopping")).toEqual(["log", "share"]);
    expect(rowActions("archived")).toEqual(["log", "share"]);
  });
  it("status from the api wins; older apis are derived", () => {
    expect(walletStatus(w({ status: "paused" }))).toBe("paused");
    expect(walletStatus(w({ stopping: true }))).toBe("stopping");
    expect(walletStatus(w({ in_book: false }))).toBe("stopping");
    expect(walletStatus(w({ in_book: false, open_copies: 0 }))).toBe("stopped");
    expect(walletStatus(w({ archived_ms: 5 }))).toBe("archived");
    expect(walletStatus(w({}))).toBe("running");
  });
  it("tabs and counts: running+paused | stopping+stopped | archived", () => {
    const list = [w({ status: "running" }), w({ status: "paused" }), w({ status: "stopping" }), w({ status: "stopped" }), w({ status: "archived" })];
    expect(tabCounts(list)).toEqual({ running: 2, stopped: 2, archived: 1 });
    expect(inTab(list, "archived")).toHaveLength(1);
    expect(tabOf("paused")).toBe("running");
  });
  it("archive needs the typed word", () => {
    expect(archiveConfirmed(" Archive ")).toBe(true);
    expect(archiveConfirmed("archiv")).toBe(false);
    expect(archiveConfirmed("")).toBe(false);
  });
});
