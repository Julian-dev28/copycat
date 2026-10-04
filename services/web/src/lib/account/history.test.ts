import { describe, expect, it } from "vitest";
import { normalizeBalances, normalizeFills, normalizeOrderRows, normalizeTransfers, transferLabel } from "./history";

const ME = "0xaaaa000000000000000000000000000000000001";
const YOU = "0xbbbb000000000000000000000000000000000002";

describe("normalizeFills", () => {
  it("reads contract rows and raw HL rows, newest first, dropping junk", () => {
    const out = normalizeFills([
      { time_ms: 1, coin: "BTC", side: "B", dir: "Open Long", px: 100, sz: 2, notional_usd: 200, closed_pnl_usd: 0, fee_usd: 0.1 },
      { time: 5, coin: "ETH", side: "A", dir: "Close Long", px: "10", sz: "3", closedPnl: "4.5", fee: "0.02" },
      { time: 9, coin: "SOL", side: "X", px: 1, sz: 1 },
      null,
    ]);
    expect(out.map((f) => f.coin)).toEqual(["ETH", "BTC"]);
    expect(out[0]).toMatchObject({ time_ms: 5, px: 10, sz: 3, notional_usd: 30, closed_pnl_usd: 4.5, fee_usd: 0.02 });
  });

  it("accepts a {rows} wrapper", () => {
    expect(normalizeFills({ rows: [{ time: 1, coin: "BTC", side: "B", px: 1, sz: 1 }] })).toHaveLength(1);
    expect(normalizeFills("nope")).toEqual([]);
  });
});

describe("normalizeTransfers", () => {
  it("labels direction from HL ledger deltas", () => {
    const out = normalizeTransfers([
      { time: 1, hash: "0x1", delta: { type: "deposit", usdc: "100.0" } },
      { time: 2, hash: "0x2", delta: { type: "withdraw", usdc: "40", fee: "1" } },
      { time: 3, hash: "0x3", delta: { type: "send", usdc: "5", user: ME, destination: YOU } },
      { time: 4, hash: "0x4", delta: { type: "send", usdc: "7", user: YOU, destination: ME } },
      { time: 5, delta: { type: "accountClassTransfer", usdc: "9", toPerp: true } },
      { time: 6, delta: { type: "deposit" } },
    ], ME.toUpperCase().replace("0X", "0x"));
    expect(out.map((t) => [t.time_ms, t.direction, t.amount_usd, t.counterparty])).toEqual([
      [5, "internal", 9, null],
      [4, "in", 7, YOU],
      [3, "out", 5, YOU],
      [2, "out", 40, null],
      [1, "in", 100, null],
    ]);
  });

  it("keeps contract rows as given", () => {
    const out = normalizeTransfers([{ time_ms: 1, type: "usdSend", amount_usd: 12, direction: "out", counterparty: YOU, hash: null }], ME);
    expect(out[0]).toEqual({ time_ms: 1, type: "usdSend", amount_usd: 12, direction: "out", counterparty: YOU, hash: null });
    expect(transferLabel("usdSend")).toBe("Send");
    expect(transferLabel("cStakingTransfer")).toBe("C Staking Transfer");
  });
});

describe("normalizeBalances", () => {
  it("values USDC at par, sorts by value, hides zero lines", () => {
    const out = normalizeBalances([
      { coin: "PURR", total: "100", hold: "0", usd_value: 20 },
      { coin: "USDC", total: "500.5", hold: "10" },
      { coin: "DUST", total: "0", hold: "0" },
      { coin: "MYSTERY", total: "3" },
    ]);
    expect(out.map((b) => [b.coin, b.usd_value])).toEqual([["USDC", 500.5], ["PURR", 20], ["MYSTERY", null]]);
    expect(out[0].hold).toBe(10);
  });
});

describe("normalizeOrderRows", () => {
  it("delegates to the scout order normalizer", () => {
    const out = normalizeOrderRows({ rows: [{ oid: 1, coin: "BTC", side: "B", limitPx: "100", sz: "2", timestamp: 5 }] });
    expect(out[0]).toMatchObject({ coin: "BTC", side: "buy", px: 100, notional: 200, status: null });
  });

  it("keeps HL historicalOrders status, newest status first", async () => {
    const { orderStatusLabel } = await import("./history");
    const out = normalizeOrderRows({ kind: "orders", rows: [
      { oid: 1, coin: "BTC", side: "B", limitPx: "100", sz: "0", origSz: "2", timestamp: 5, status: "filled", status_ms: 9 },
      { oid: 2, coin: "ETH", side: "A", limitPx: "10", sz: "1", origSz: "1", timestamp: 6, status: "marginCanceled", status_ms: 20 },
    ] });
    expect(out.map((o) => [o.oid, o.status])).toEqual([[2, "marginCanceled"], [1, "filled"]]);
    expect(orderStatusLabel("marginCanceled")).toBe("Margin canceled");
    expect(orderStatusLabel(null)).toBe("—");
  });
});
