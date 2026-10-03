import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiFetch, getApiBase, onUnauthorized } from "./client";
import { clearStoredToken, setStoredToken } from "./token";

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("getApiBase", () => {
  it("defaults to http://localhost:8787 when NEXT_PUBLIC_COPYCAT_API is unset", () => {
    const prev = process.env.NEXT_PUBLIC_COPYCAT_API;
    delete process.env.NEXT_PUBLIC_COPYCAT_API;
    expect(getApiBase()).toBe("http://localhost:8787");
    if (prev !== undefined) process.env.NEXT_PUBLIC_COPYCAT_API = prev;
  });

  it("strips a trailing slash from a configured base", () => {
    const prev = process.env.NEXT_PUBLIC_COPYCAT_API;
    process.env.NEXT_PUBLIC_COPYCAT_API = "https://example.test/";
    expect(getApiBase()).toBe("https://example.test");
    process.env.NEXT_PUBLIC_COPYCAT_API = prev;
  });
});

describe("apiFetch auth header", () => {
  beforeEach(() => {
    clearStoredToken();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ok: true })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearStoredToken();
  });

  it("attaches no Authorization header when no token is stored", async () => {
    await apiFetch("/api/health");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("attaches `Bearer <token>` from localStorage by default", async () => {
    setStoredToken("secret-token");
    await apiFetch("/api/health");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("an explicit token option overrides the stored one", async () => {
    setStoredToken("stored-token");
    await apiFetch("/api/health", { token: "explicit-token" });
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer explicit-token");
  });

  it("an explicit null token sends no Authorization header even if one is stored", async () => {
    setStoredToken("stored-token");
    await apiFetch("/api/health", { token: null });
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("requests the configured base URL + path", async () => {
    await apiFetch("/api/health");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(`${getApiBase()}/api/health`);
  });
});

describe("apiFetch 401 handling", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "missing bearer token" }, { status: 401 })),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("throws an ApiError with status 401", async () => {
    await expect(apiFetch("/api/status")).rejects.toMatchObject({ status: 401 } satisfies Partial<ApiError>);
  });

  it("notifies onUnauthorized subscribers exactly once per call", async () => {
    const cb = vi.fn();
    const unsubscribe = onUnauthorized(cb);
    await expect(apiFetch("/api/status")).rejects.toThrow();
    expect(cb).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("stops notifying after unsubscribe", async () => {
    const cb = vi.fn();
    const unsubscribe = onUnauthorized(cb);
    unsubscribe();
    await expect(apiFetch("/api/status")).rejects.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });
});

describe("apiFetch non-401 errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("surfaces the `detail` field from a JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "409: too many leaders" }, { status: 409 })),
    );
    await expect(apiFetch("/api/leaders")).rejects.toMatchObject({
      status: 409,
      message: "409: too many leaders",
    });
  });

  it("falls back to the status line when the body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not json", { status: 500, statusText: "Internal Server Error" })),
    );
    await expect(apiFetch("/api/status")).rejects.toMatchObject({ status: 500 });
  });
});

describe("api.patchSettings leader_overrides null clearing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("serializes a null override as JSON null, not dropping the key", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.patchSettings({ leader_overrides: { "0xabc": null } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
    const parsedBody = JSON.parse(init.body as string);
    expect(parsedBody).toHaveProperty("leader_overrides.0xabc", null);
    expect(Object.prototype.hasOwnProperty.call(parsedBody.leader_overrides, "0xabc")).toBe(true);
  });

  it("serializes a real override object alongside other patched fields", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.patchSettings({
      enabled: true,
      leader_overrides: { "0xabc": { leverage: 10, leverage_mode: "fixed" } },
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsedBody = JSON.parse(init.body as string);
    expect(parsedBody.enabled).toBe(true);
    expect(parsedBody.leader_overrides["0xabc"]).toEqual({ leverage: 10, leverage_mode: "fixed" });
  });

  it("sets Content-Type: application/json on bodied requests", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await api.patchSettings({ enabled: true });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

describe("api.removeLeader", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("URL-encodes the address and uses DELETE", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await api.removeLeader("0xABC");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${getApiBase()}/api/leaders/0xABC`);
    expect(init.method).toBe("DELETE");
  });
});
