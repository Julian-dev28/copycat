import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { accountErrorText, isOpenCopiesConflict } from "./errors";
import { secretFetch } from "./secretFetch";

afterEach(() => vi.unstubAllGlobals());

describe("accountErrorText", () => {
  it("names each failure in plain words", () => {
    expect(accountErrorText(new ApiError(401, "invalid passphrase"))).toMatch(/Wrong passphrase/);
    expect(accountErrorText(new ApiError(429, "too many attempts"))).toMatch(/5 key operations a minute/);
    expect(accountErrorText(new ApiError(404, "Not Found"), "transfer")).toMatch(/^api too old: .*transfer/);
    expect(accountErrorText(new ApiError(409, "fund it first"))).toMatch(/fund it first/);
    expect(accountErrorText(null)).toBe("");
    expect(isOpenCopiesConflict(new ApiError(409, "x"))).toBe(true);
    expect(isOpenCopiesConflict(new ApiError(400, "x"))).toBe(false);
  });
});

describe("secretFetch", () => {
  const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("keeps a wrong passphrase a form error (no token re-check)", async () => {
    const f = vi.fn(async () => res(401, { detail: "invalid passphrase" }));
    const global = vi.fn(async () => res(200, {}));
    vi.stubGlobal("fetch", global);
    await expect(secretFetch("/api/accounts/transfer", { passphrase: "x" }, f as unknown as typeof fetch)).rejects.toMatchObject({ status: 401, message: "invalid passphrase" });
    expect(global).not.toHaveBeenCalled();
  });

  it("re-checks a real token 401 with a GET, never resending the secret", async () => {
    const f = vi.fn(async () => res(401, { detail: "bad token" }));
    const global = vi.fn(async () => res(401, { detail: "bad token" }));
    vi.stubGlobal("fetch", global);
    await expect(secretFetch("/api/accounts/transfer", { passphrase: "x" }, f as unknown as typeof fetch)).rejects.toMatchObject({ status: 401 });
    expect(global).toHaveBeenCalledTimes(1);
    const [url, init] = global.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/settings$/);
    expect(init.body).toBeUndefined();
  });

  it("returns the parsed body on success", async () => {
    const f = vi.fn(async () => res(200, { ok: true }));
    expect(await secretFetch("/x", {}, f as unknown as typeof fetch)).toEqual({ ok: true });
  });
});
