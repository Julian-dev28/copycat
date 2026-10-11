import { describe, expect, it } from "vitest";
import { agentView, canRefresh, pickActive } from "./agent";
import { checkLabel, checkPassphrase, passphraseStrength } from "./passphrase";
import type { TradingAccount } from "./types";

const NOW = 1_760_000_000_000;
const DAY = 86_400_000;
const acc = (p: Partial<TradingAccount>): TradingAccount => ({
  id: "a", label: "A", kind: "connected_signed", address: "0x1", agent_status: "active", active: false, created_ms: 0, has_main_key: false, ...p,
});

describe("agentView", () => {
  it("counts days left and flips to expiring at 30d", () => {
    expect(agentView(acc({ agent_valid_until_ms: NOW + 90 * DAY }), NOW)).toMatchObject({ status: "active", label: "Active", daysLeft: 90 });
    expect(agentView(acc({ agent_valid_until_ms: NOW + 12 * DAY }), NOW)).toMatchObject({ status: "expiring", label: "Expires in 12d", tone: "warning" });
    expect(agentView(acc({ agent_valid_until_ms: NOW + 3_600_000 }), NOW).label).toBe("Expires today");
  });

  it("trusts the date over a stale 'active'", () => {
    expect(agentView(acc({ agent_valid_until_ms: NOW - DAY }), NOW)).toMatchObject({ status: "expired", label: "Expired", tone: "danger" });
  });

  it("explains a missing agent per kind", () => {
    expect(agentView(acc({ agent_status: "missing", kind: "created" }), NOW).hint).toMatch(/deposit, then refresh/);
    expect(agentView(acc({ agent_status: "missing", kind: "connected_key" }), NOW).hint).toMatch(/new API wallet key/);
    expect(agentView(acc({ agent_status: "unknown" }), NOW).label).toBe("Unknown");
  });

  it("offers refresh only when it helps", () => {
    expect(canRefresh(agentView(acc({ agent_valid_until_ms: NOW + 90 * DAY }), NOW))).toBe(false);
    expect(canRefresh(agentView(acc({ agent_valid_until_ms: NOW + 5 * DAY }), NOW))).toBe(true);
    expect(canRefresh(agentView(acc({ agent_status: "missing" }), NOW))).toBe(true);
  });

  it("pickActive never guesses", () => {
    expect(pickActive([acc({ id: "x" }), acc({ id: "y", active: true })])?.id).toBe("y");
    expect(pickActive([acc({ id: "x" })])).toBeNull();
    expect(pickActive(undefined)).toBeNull();
  });
});

describe("passphrase", () => {
  it("rates strength", () => {
    expect(passphraseStrength("short")).toBe("too_short");
    expect(passphraseStrength("aaaaaaaaaaaaaaaa")).toBe("weak");
    expect(passphraseStrength("abcdefghijkl")).toBe("weak");
    expect(passphraseStrength("Tr0ub4dor&3xyz")).toBe("fair");
    expect(passphraseStrength("correct horse battery staple 42")).toBe("strong");
  });

  it("checks length and match", () => {
    expect(checkPassphrase("x".repeat(11), "x".repeat(11)).error).toMatch(/at least 12/);
    expect(checkPassphrase("x".repeat(12), "y".repeat(12)).error).toMatch(/do not match/);
    expect(checkPassphrase("x".repeat(12), "x".repeat(12)).ok).toBe(true);
    expect(checkLabel("  ")).toMatch(/name/);
    expect(checkLabel("x".repeat(61))).toMatch(/under 60/);
    expect(checkLabel("Main")).toBeNull();
  });
});
