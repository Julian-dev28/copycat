import { describe, expect, it, vi } from "vitest";
import { qrPath } from "./qr";
import { backupFilename, backupText, clearIfStill, copySecret } from "./secrets";

function board(initial = "", canRead = true) {
  let text = initial;
  return {
    get: () => text,
    writeText: vi.fn(async (t: string) => {
      text = t;
    }),
    readText: canRead ? vi.fn(async () => text) : vi.fn(async () => { throw new Error("denied"); }),
  };
}

describe("copySecret", () => {
  it("copies, then clears after the delay", async () => {
    const cb = board();
    let fire: (() => void) | null = null;
    const cancel = vi.fn();
    await copySecret("0xsecret", cb, 60_000, (fn, ms) => {
      expect(ms).toBe(60_000);
      fire = fn;
      return cancel;
    });
    expect(cb.get()).toBe("0xsecret");
    (fire as unknown as () => void)();
    await vi.waitFor(() => expect(cb.get()).toBe(""));
  });

  it("throws in plain words when there is no clipboard", async () => {
    await expect(copySecret("x", undefined)).rejects.toThrow(/copy it by hand/);
  });
});

describe("clearIfStill", () => {
  it("leaves something the user copied since alone", async () => {
    const cb = board("something else");
    expect(await clearIfStill("0xsecret", cb)).toBe(false);
    expect(cb.get()).toBe("something else");
  });

  it("clears when it cannot read the clipboard", async () => {
    const cb = board("0xsecret", false);
    expect(await clearIfStill("0xsecret", cb)).toBe(true);
    expect(cb.get()).toBe("");
  });
});

describe("backup file", () => {
  it("has the address, the key and the warning", () => {
    const t = backupText({ label: "Main", address: "0xabc", privateKey: "0xkey", warning: "shown once", nowMs: 0 });
    expect(t).toContain("0xabc");
    expect(t).toContain("0xkey");
    expect(t).toContain("shown once");
    expect(t).toContain("1970-01-01T00:00:00.000Z");
  });

  it("names the file after the label and address", () => {
    expect(backupFilename("My Main  Wallet!", "0xABCDEF0123")).toBe("copycat-backup-my-main-wallet-abcdef.txt");
    expect(backupFilename("***", "0x123456789")).toBe("copycat-backup-wallet-123456.txt");
  });
});

describe("qrPath", () => {
  it("draws a square code with a 4-module quiet zone", () => {
    const { size, d } = qrPath("0x7a3f2c19e04b8d5a6c1e9f20b3d4a5c6e7f80911");
    expect(size).toBeGreaterThanOrEqual(21 + 8);
    expect(d.startsWith("M4 4h7")).toBe(true); // top-left finder pattern: 7 dark modules
    expect(d).not.toMatch(/NaN|undefined/);
  });
});
