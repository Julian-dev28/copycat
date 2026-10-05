import { describe, expect, it } from "vitest";
import { apiCaps, buildCopyRequest, effective, inherit, initialDraft, switchesSource, ticketAction, walletSource, type TicketDraft } from "./draft";
import { demoSettings } from "./fixtures";
import { globalSummary, leverageText, sizingText } from "./globalSummary";

const V7 = { v7: true, smallMode: true, v8: false };
const OLD = { v7: false, smallMode: true, v8: false };
const custom: TicketDraft = {
  source: "custom", amountText: "50", mode: "target", leverage: 10, marginMode: null, maxWorseEntryPct: null, smallMode: null, onlyNew: null, direction: null, allow: null, block: null,
};
const A = "0x" + "a".repeat(40);

describe("request bodies, contract v7", () => {
  it("Use global sends only the source (the api ignores the rest)", () => {
    expect(buildCopyRequest({ ...custom, source: "global", amountText: "" }, V7)).toEqual({ settings_source: "global" });
  });

  it("Use global is impossible on a pre-v7 api: no body", () => {
    expect(buildCopyRequest({ ...custom, source: "global" }, OLD)).toBeNull();
  });

  it("Custom + Set leverage: allocation, target leverage, nothing inherited is sent", () => {
    expect(buildCopyRequest(custom, V7)).toEqual({ settings_source: "custom", allocation_usd: 50, exposure_mode: "target", target_leverage: 10 });
  });

  it("Custom + Follow their leverage: leverage_mode match, no target_leverage", () => {
    const b = buildCopyRequest({ ...custom, mode: "match" }, V7)!;
    expect(b.leverage_mode).toBe("match");
    expect(b).not.toHaveProperty("target_leverage");
  });

  it("Custom overrides are sent only when set, only_new_positions per wallet", () => {
    const b = buildCopyRequest({ ...custom, marginMode: "cross", maxWorseEntryPct: 3, smallMode: "skip", onlyNew: true }, V7)!;
    expect(b).toMatchObject({ margin_mode: "cross", max_worse_entry_pct: 3, small_account_mode: "skip", only_new_positions: true });
    expect(buildCopyRequest({ ...custom, onlyNew: false }, V7)!.only_new_positions).toBe(false);
  });

  it("Custom needs an amount", () => {
    expect(buildCopyRequest({ ...custom, amountText: "" }, V7)).toBeNull();
  });

  it("pre-v7 api: no v7 keys (extra=forbid would 422)", () => {
    const b = buildCopyRequest({ ...custom, mode: "match", onlyNew: true }, OLD)!;
    expect(b).not.toHaveProperty("settings_source");
    expect(b).not.toHaveProperty("leverage_mode");
    expect(b).not.toHaveProperty("only_new_positions");
    expect(buildCopyRequest({ ...custom, smallMode: "bump" }, { v7: true, smallMode: false, v8: false })).not.toHaveProperty("small_account_mode");
  });

  it("apiCaps reads the contract version", () => {
    expect(apiCaps(demoSettings())).toEqual(V7);
    expect(apiCaps({ ...demoSettings(), contract_version: 5 }).v7).toBe(false);
  });
});

describe("inherit resets", () => {
  it("clears just that field, and the Settings value applies again", () => {
    const s = { ...demoSettings(), margin_mode: "isolated" as const, max_worse_entry_pct: 10 };
    const d = { ...custom, marginMode: "cross" as const, maxWorseEntryPct: 2 };
    expect(effective(d, s)).toMatchObject({ marginMode: "cross", maxWorseEntryPct: 2 });
    const back = inherit(d, "marginMode");
    expect(back.marginMode).toBeNull();
    expect(back.maxWorseEntryPct).toBe(2);
    expect(effective(back, s)).toMatchObject({ marginMode: "isolated", maxWorseEntryPct: 2 });
    expect(buildCopyRequest(back, V7)).not.toHaveProperty("margin_mode");
  });

  it("Use global ignores any custom field values", () => {
    const s = { ...demoSettings(), only_new_positions: false };
    expect(effective({ ...custom, source: "global", onlyNew: true }, s).onlyNew).toBe(false);
  });
});

describe("saved terms and buttons", () => {
  it("source: the api's settings_source, else an allocation means custom, else in-book means global", () => {
    expect(walletSource({ settings_source: "global", allocation_usd: 50 }, undefined, true)).toBe("global");
    expect(walletSource({ allocation_usd: 50 }, undefined, true)).toBe("custom");
    expect(walletSource(null, undefined, true)).toBe("global");
    expect(walletSource(null, undefined, false)).toBe("custom");
  });

  it("initialDraft: overrides prefill, unset fields stay inherited (null)", () => {
    const s = demoSettings();
    s.leaders = [A];
    s.leader_overrides[A] = { allocation_usd: 75, exposure_mode: "target", target_leverage: 8, margin_mode: "cross" };
    expect(initialDraft(s, A)).toMatchObject({ source: "custom", amountText: "75", leverage: 8, marginMode: "cross", maxWorseEntryPct: null, onlyNew: null });
    s.leader_overrides = {};
    expect(initialDraft(s, A).source).toBe("global");
  });

  it("copy / update / unchanged, global compares only the source", () => {
    expect(ticketAction(custom, null, false)).toBe("copy");
    expect(ticketAction(custom, custom, true)).toBe("unchanged");
    expect(ticketAction({ ...custom, amountText: "75" }, custom, true)).toBe("update");
    expect(ticketAction({ ...custom, onlyNew: true }, custom, true)).toBe("update");
    const g = { ...custom, source: "global" as const };
    expect(ticketAction({ ...g, amountText: "999" }, g, true)).toBe("unchanged");
  });

  it("switching a running wallet's source is flagged for the confirm", () => {
    const g = { ...custom, source: "global" as const };
    expect(switchesSource(custom, g, true)).toBe(true);
    expect(switchesSource(custom, custom, true)).toBe(false);
    expect(switchesSource(custom, g, false)).toBe(false);
  });
});

describe("global summary", () => {
  it("reads every Settings value that will apply", () => {
    const s = { ...demoSettings(), sizing_mode: "fixed_margin" as const, fixed_margin_usd: 5, leverage_mode: "max" as const, max_position_leverage: 20 };
    expect(sizingText(s)).toBe("Fixed margin, $5.00 per copy");
    expect(leverageText(s)).toBe("Each coin's max, cap 20x");
    expect(globalSummary(s).map((r) => r.label)).toEqual(["Sizing", "Leverage", "Margin", "Max worse entry", "Under $10", "Only new positions"]);
    expect(leverageText({ ...s, sizing_mode: "allocation", exposure_mode: "target", target_leverage: 7 })).toBe("7x on his book (cap 20x)");
  });
});
