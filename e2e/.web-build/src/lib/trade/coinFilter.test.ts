import { describe, expect, it } from "vitest";
import { addCoin, applyCoinFilter, canonicalCoin, coinVerdict, parseCoins, suggestCoins } from "./coinFilter";
import { localPreview } from "./preview";

const prev = localPreview({
  allocationUsd: 1_000, mode: "target", targetLeverage: 2, marginMode: "isolated", smallMode: "skip", leaderEquityUsd: 10_000,
  positions: [
    { coin: "BTC", side: "long", notional_usd: 5_000, leverage: 5 },
    { coin: "ETH", side: "short", notional_usd: 3_000, leverage: 5 },
    { coin: "xyz:TSLA", side: "long", notional_usd: 2_000, leverage: 3 },
  ],
});

describe("coin filters (engine coin_allowed rule)", () => {
  it("blocklist wins, allowlist admits only its coins, case-insensitive, dex prefix kept", () => {
    expect(coinVerdict("BTC", [], ["btc"])).toBe("blocked");
    expect(coinVerdict("ETH", ["BTC"], [])).toBe("not_allowed");
    expect(coinVerdict("btc", ["BTC"], ["BTC"])).toBe("blocked");
    expect(coinVerdict("xyz:TSLA", ["XYZ:tsla"], [])).toBeNull();
    expect(coinVerdict("TSLA", ["xyz:TSLA"], [])).toBe("not_allowed");
    expect(coinVerdict("SOL", [], [])).toBeNull();
  });
  it("marks filtered slices skipped with the reason and recomputes totals", () => {
    const p = applyCoinFilter(prev, [], ["ETH"]);
    const eth = p.copies.find((c) => c.coin === "ETH")!;
    expect(eth).toMatchObject({ status: "skipped", notionalUsd: 0, filtered: true, reason: "filtered: on Never these coins" });
    expect(p.copied).toBe(2);
    expect(p.exposureUsd).toBeCloseTo(prev.exposureUsd - prev.copies[1].notionalUsd);
    // the others keep their size: the engine skips, it does not re-spread
    expect(p.copies[0].notionalUsd).toBe(prev.copies[0].notionalUsd);
  });
  it("allowlist filters everything else; no lists is a no-op; idempotent", () => {
    const p = applyCoinFilter(prev, ["BTC"], []);
    expect(p.copies.filter((c) => c.filtered).map((c) => c.coin)).toEqual(["ETH", "xyz:TSLA"]);
    expect(applyCoinFilter(prev, [], [])).toBe(prev);
    expect(applyCoinFilter(p, ["BTC"], [])).toEqual(p);
  });
  it("chip parsing: canonical spelling, dedupe, paste of several", () => {
    expect(canonicalCoin("kpepe", ["kPEPE"])).toBe("kPEPE");
    expect(canonicalCoin(" XYZ:tsla ")).toBe("xyz:TSLA");
    expect(canonicalCoin("$sol")).toBe("SOL");
    expect(canonicalCoin("bt c")).toBeNull();
    expect(addCoin(["BTC"], "btc")).toEqual(["BTC"]);
    expect(parseCoins("btc, eth  sol;btc")).toEqual(["BTC", "ETH", "SOL"]);
  });
  it("autocomplete: his coins first, prefix before substring, chosen excluded", () => {
    const s = suggestCoins("e", ["ETH", "BTC"], ["ENA", "ETH", "PENDLE"], []);
    expect(s[0]).toEqual({ coin: "ETH", his: true });
    expect(s.map((x) => x.coin)).toEqual(["ETH", "ENA", "PENDLE"]);
    expect(suggestCoins("", ["BTC"], ["BTC", "SOL"], ["SOL"]).map((x) => x.coin)).toEqual(["BTC"]);
    expect(suggestCoins("tsla", [], ["xyz:TSLA"], [])[0].coin).toBe("xyz:TSLA");
  });
});
