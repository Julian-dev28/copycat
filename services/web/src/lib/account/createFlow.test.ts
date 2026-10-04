import { describe, expect, it } from "vitest";
import { canClose, createReducer, holdsKey, initialCreate, type CreateState } from "./createFlow";
import type { CreateAccountResponse } from "./types";

const KEY = `0x${"5e".repeat(32)}`;
const RES: CreateAccountResponse = {
  account: { id: "a1", label: "Main", kind: "created", address: "0x1111111111111111111111111111111111111111", agent_status: "missing", active: false, created_ms: 1, has_main_key: true },
  private_key: KEY,
  backup_warning: "shown once",
};

const created = () => createReducer(initialCreate, { type: "created", res: RES });

describe("createReducer", () => {
  it("holds the key only in the reveal step, hidden until asked", () => {
    const s = created();
    expect(s.step).toBe("reveal");
    expect(holdsKey(s)).toBe(true);
    expect(s.step === "reveal" && s.revealed).toBe(false);
    const shown = createReducer(s, { type: "reveal" });
    expect(shown.step === "reveal" && shown.revealed).toBe(true);
  });

  it("refuses to close while the key is unsaved", () => {
    const s = created();
    expect(canClose(s)).toBe(false);
    expect(createReducer(s, { type: "close" })).toBe(s);
  });

  it("refuses to continue until 'I saved my key' is ticked", () => {
    const s = created();
    expect(createReducer(s, { type: "continue" })).toBe(s);
  });

  it("drops the key when the dialog closes after saving", () => {
    const saved = createReducer(created(), { type: "toggleSaved", saved: true });
    const closed = createReducer(saved, { type: "close" });
    expect(closed).toEqual(initialCreate);
    expect(holdsKey(closed)).toBe(false);
    expect(JSON.stringify(closed)).not.toContain(KEY);
  });

  it("drops the key when moving on to the fund step, and the fund step closes", () => {
    let s: CreateState = createReducer(created(), { type: "toggleSaved", saved: true });
    s = createReducer(s, { type: "continue" });
    expect(s.step).toBe("fund");
    expect(JSON.stringify(s)).not.toContain(KEY);
    expect(canClose(s)).toBe(true);
    expect(createReducer(s, { type: "close" })).toEqual(initialCreate);
  });

  it("unticking blocks the close again", () => {
    let s: CreateState = createReducer(created(), { type: "toggleSaved", saved: true });
    s = createReducer(s, { type: "toggleSaved", saved: false });
    expect(canClose(s)).toBe(false);
  });
});
