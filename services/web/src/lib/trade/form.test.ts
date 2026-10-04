import { describe, expect, it } from "vitest";
import { buildCopyRequest, checkAmount, chipAmount, initialDraft, maxInvest, parseInvest, ticketAction, type TicketDraft } from "./form";
import { demoSettings } from "./fixtures";

const draft: TicketDraft = { amountText: "50", mode: "target", leverage: 10, marginMode: "isolated", maxWorseEntryPct: 10, smallMode: "concentrate" };

describe("request bodies (WalletCopyRequest, extra=forbid)", () => {
  it("Set leverage sends target_leverage", () => {
    expect(buildCopyRequest(draft, 50, { smallModeSupported: true })).toEqual({
      allocation_usd: 50, exposure_mode: "target", target_leverage: 10, margin_mode: "isolated", max_worse_entry_pct: 10,
      small_account_mode: "concentrate",
    });
  });

  it("Follow their leverage never sends target_leverage", () => {
    const b = buildCopyRequest({ ...draft, mode: "match" }, 50, { smallModeSupported: true });
    expect(b).not.toHaveProperty("target_leverage");
    expect(b.exposure_mode).toBe("match");
  });

  it("an api without small_account_mode never gets the key (it would 422)", () => {
    expect(buildCopyRequest(draft, 50, { smallModeSupported: false })).not.toHaveProperty("small_account_mode");
  });

  it("rounds the allocation to cents and clamps leverage to 1..50", () => {
    const b = buildCopyRequest({ ...draft, leverage: 80 }, 12.3456, { smallModeSupported: false });
    expect(b.allocation_usd).toBe(12.35);
    expect(b.target_leverage).toBe(50);
  });
});

describe("amounts from $10 to $10M", () => {
  it("parses plain, comma, $ and k/m suffixes", () => {
    expect(parseInvest("1,000")).toBe(1000);
    expect(parseInvest("$2.5k")).toBe(2500);
    expect(parseInvest("10m")).toBe(10_000_000);
    expect(parseInvest("")).toBeNull();
    expect(parseInvest("abc")).toBeNull();
    expect(parseInvest("-5")).toBeNull();
  });

  it("max = free margin + this wallet's own margin, floored to cents", () => {
    expect(maxInvest(100.129)).toBe(100.12);
    expect(maxInvest(40, 10)).toBe(50);
    expect(maxInvest(null)).toBeNull();
    expect(maxInvest(-5)).toBe(0);
  });

  it("chips are % of max, floored, Max is exactly max", () => {
    expect(chipAmount(1_000_000, 25)).toBe(250_000);
    expect(chipAmount(20.01, 75)).toBe(15);
    expect(chipAmount(20.01, 100)).toBe(20.01);
    expect(chipAmount(0, 50)).toBeNull();
  });

  it("checkAmount: blank and tiny are errors, over free margin is a warning", () => {
    expect(checkAmount(null, 100)).toEqual({ ok: false, error: "Enter an amount" });
    expect(checkAmount(0.5, 100).ok).toBe(false);
    expect(checkAmount(150, 100)).toMatchObject({ ok: true, warn: expect.stringMatching(/free margin/) });
    expect(checkAmount(100, 100)).toEqual({ ok: true, warn: null });
  });
});

describe("which button", () => {
  it("new wallet -> copy; invested and changed -> update; same -> unchanged", () => {
    expect(ticketAction(draft, 50, null, false)).toBe("copy");
    expect(ticketAction(draft, 50, draft, true)).toBe("unchanged");
    expect(ticketAction(draft, 75, draft, true)).toBe("update");
    expect(ticketAction({ ...draft, leverage: 12 }, 50, draft, true)).toBe("update");
  });

  it("leverage changes don't count while following his leverage", () => {
    const m = { ...draft, mode: "match" as const };
    expect(ticketAction({ ...m, leverage: 30 }, 50, m, true)).toBe("unchanged");
  });

  it("initialDraft prefills an invested wallet and defaults a new one", () => {
    const s = demoSettings();
    const a = "0x" + "a".repeat(40);
    s.leader_overrides[a] = { allocation_usd: 75, exposure_mode: "target", target_leverage: 8 };
    expect(initialDraft(s, a)).toMatchObject({ amountText: "75", mode: "target", leverage: 8 });
    expect(initialDraft(s, "0x" + "b".repeat(40))).toMatchObject({ amountText: "", mode: "match", leverage: 5, smallMode: "concentrate" });
  });
});
