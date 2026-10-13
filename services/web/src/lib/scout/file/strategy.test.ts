import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { demoFile, isBusy, parseFingerprint, whatIfErrorText } from "./source";
import { fixtureFingerprint, fixtureTheses } from "./fixtures";
import { buildingText, fileView } from "./state";
import { buildToc, contextChips, hasClaudeThesis, isStale, keyNumbers, orderTheses, slugify, thesisCommand } from "./strategy";

const NOW = Date.UTC(2026, 9, 4, 12, 0);
const ADDR = "0xe2823659be02e0f48a4660e4da008b5e1abfdf29";

describe("theses", () => {
  it("keeps the newest per source, ta first", () => {
    const [ta, cc] = fixtureTheses(ADDR, NOW);
    const older = { ...ta, created_ms: ta.created_ms - 1000, title: "old" };
    expect(orderTheses([cc, older, ta]).map((t) => t.title)).toEqual([ta.title, cc.title]);
  });

  it("shows the Claude Code hint only when no claude_code thesis exists", () => {
    expect(hasClaudeThesis(fixtureTheses(ADDR, NOW))).toBe(true);
    expect(hasClaudeThesis(fixtureTheses(ADDR, NOW, false))).toBe(false);
    expect(thesisCommand("0xABC")).toBe("/copycat-thesis 0xabc");
  });

  it("is stale only when a newer fingerprint exists than the one it cites", () => {
    const fp = fixtureFingerprint(ADDR, NOW);
    const [ta] = fixtureTheses(ADDR, NOW);
    expect(isStale(ta, fp)).toBe(false);                                   // same fingerprint
    expect(isStale({ ...ta, fingerprint_as_of_ms: fp.as_of_ms - 1 }, fp)).toBe(true);
    expect(isStale({ ...ta, fingerprint_as_of_ms: fp.as_of_ms + 1 }, fp)).toBe(false);
    expect(isStale({ ...ta, fingerprint_as_of_ms: null }, fp)).toBe(false); // can't prove it, don't claim it
  });
});

describe("table of contents", () => {
  it("slugifies headings deterministically", () => {
    expect(slugify("Edge in one sentence")).toBe("edge-in-one-sentence");
    expect(slugify("Sizing & risk")).toBe("sizing-risk");
    expect(slugify("  Multiple   spaces! ")).toBe("multiple-spaces");
  });

  it("parses ## and ### headings in order, skipping deeper levels", () => {
    const md = ["## Edge in one sentence", "body", "### A sub-point", "## How they enter", "#### too deep"].join("\n");
    expect(buildToc(md)).toEqual([
      { id: "edge-in-one-sentence", text: "Edge in one sentence", level: 2 },
      { id: "a-sub-point", text: "A sub-point", level: 3 },
      { id: "how-they-enter", text: "How they enter", level: 2 },
    ]);
  });

  it("de-dupes repeated headings with a numeric suffix", () => {
    const md = ["## Risks", "## Risks"].join("\n");
    expect(buildToc(md).map((t) => t.id)).toEqual(["risks", "risks-2"]);
  });
});

describe("fingerprint shaping", () => {
  it("renders key numbers with dashes for nulls", () => {
    const fp = { ...fixtureFingerprint(ADDR, NOW), payoff_ratio: null, win_rate_pct: undefined };
    const k = Object.fromEntries(keyNumbers(fp).map((x) => [x.label, x.value]));
    expect(k["Payoff ratio"]).toBe("—");
    expect(k["Win rate"]).toBe("—");
    expect(k["Median hold"]).toBe("7.5h");
  });

  it("context chips read the entry context", () => {
    expect(contextChips({ trend_aligned: false, breakout: true, rsi_14: 71.6, move_24h_pct: -2.34, hour_utc: 7 })).toEqual([
      "against trend",
      "breakout",
      "RSI 72",
      "24h -2.3%",
      "07:00 UTC",
    ]);
  });
});

describe("fingerprint responses", () => {
  it("parses 200 and 202 bodies, rejects anything else", () => {
    expect(parseFingerprint(fixtureFingerprint(ADDR, NOW)).kind).toBe("ready");
    expect(parseFingerprint({ refresh_id: null, state: "running", done: 1, total: 3 }).kind).toBe("building");
    expect(() => parseFingerprint({ nope: 1 })).toThrow(ApiError);
  });

  it("the demo source answers for any valid address and 404s an invalid one", async () => {
    const src = demoFile(NOW);
    const p = await src.profile(ADDR);
    expect(p.kind === "ready" && p.profile.row.address).toBe(ADDR);
    await expect(src.fingerprint("0xnope")).rejects.toMatchObject({ status: 404 });
  });
});

describe("page states", () => {
  it("maps profile results and errors to a view", () => {
    expect(fileView("0x12", undefined, null)).toBe("invalid");
    expect(fileView(ADDR, undefined, null)).toBe("loading");
    expect(fileView(ADDR, { kind: "building", status: { refresh_id: null, state: "running", done: 0, total: 0 } }, null)).toBe("building");
    expect(fileView(ADDR, undefined, new ApiError(404, "Not Found"))).toBe("too_old");
    expect(fileView(ADDR, undefined, new ApiError(405, "Method Not Allowed"))).toBe("too_old");
    expect(fileView(ADDR, undefined, new ApiError(404, "no such trader"))).toBe("not_found");
    expect(fileView(ADDR, undefined, new ApiError(500, "boom"))).toBe("error");
    expect(buildingText({ stage: "sim", done: 40, total: 280, eta_s: 300 })).toBe("stage: sim · 40/280 · about 5 min");
  });

  it("409 from what-if reads as busy", () => {
    expect(isBusy(new ApiError(409, "busy"))).toBe(true);
    expect(whatIfErrorText(new ApiError(409, "busy"))).toMatch(/busy/);
    expect(isBusy(new ApiError(500, "x"))).toBe(false);
  });
});
