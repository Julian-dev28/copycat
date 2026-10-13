import { describe, expect, it } from "vitest";
import { NOT_A_VAULT_TEXT } from "./bits";

describe("NOT_A_VAULT_TEXT", () => {
  // research/user_consensus_2026-10.md, "Known ways copiers lose money": a copier
  // can confuse copycat's copy-sim with a real Hyperliquid vault (lockup, profit
  // share). The first-run checklist and the account page must say plainly what
  // copycat is (your own account, your own agent key, nothing pooled) and isn't.
  it("says there is no lockup, no profit share and nothing pooled", () => {
    expect(NOT_A_VAULT_TEXT).toMatch(/not a pooled vault/);
    expect(NOT_A_VAULT_TEXT).toMatch(/no lockup/);
    expect(NOT_A_VAULT_TEXT).toMatch(/no profit share/);
  });
});
