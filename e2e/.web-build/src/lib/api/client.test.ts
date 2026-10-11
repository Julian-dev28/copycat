import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiFetch, getApiBase, isNotSupported, onUnauthorized } from "./client";
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

describe("api.closeAllCopies", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("POSTs to /api/engine/close-all with the bearer token", async () => {
    setStoredToken("t");
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ closed: 2 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.closeAllCopies()).resolves.toEqual({ closed: 2 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${getApiBase()}/api/engine/close-all`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer t");
    clearStoredToken();
  });

  it("a 404 from an older api is reported as not supported", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Not Found" }, { status: 404 })));
    const err = await api.closeAllCopies().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(isNotSupported(err)).toBe(true);
  });

  it("other failures are not mistaken for not supported", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "boom" }, { status: 500 })));
    const err = await api.closeAllCopies().catch((e: unknown) => e);
    expect(isNotSupported(err)).toBe(false);
    expect(isNotSupported(new Error("x"))).toBe(false);
  });
});

describe("apiFetch network failure", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("turns a fetch rejection into ApiError(0) naming the api base", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(apiFetch("/api/status")).rejects.toMatchObject({
      status: 0,
      message: `can't reach the api at ${getApiBase()}. Is it running?`,
    });
  });
});

describe("demo write guard", () => {
  const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("reads demo mode from the current URL at call time", async () => {
    const { isDemoMode } = await import("./client");
    expect(isDemoMode("?demo=1&acct=small")).toBe(true);
    expect(isDemoMode("?demo=0")).toBe(false);
    expect(isDemoMode("")).toBe(false);
    window.history.replaceState(null, "", "/settings?demo=1");
    expect(isDemoMode()).toBe(true);
  });

  it.each(["POST", "PATCH", "PUT", "DELETE", "patch"])("blocks %s in demo before fetch", async (method) => {
    window.history.replaceState(null, "", "/settings?demo=1");
    await expect(apiFetch("/api/settings", { method, body: "{}" })).rejects.toThrow("demo mode: writes are disabled");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks every typed write endpoint in demo", async () => {
    window.history.replaceState(null, "", "/discover?demo=1");
    const writes = [
      () => api.patchSettings({ enabled: true }),
      () => api.putSettings({} as never),
      () => api.addLeader("0xabc"),
      () => api.removeLeader("0xabc"),
      () => api.haltEngine(),
      () => api.closeAllCopies(),
      () => api.startDiscoveryRun({ sim_equity_usd: 1000, top_n: 25 } as never),
    ];
    for (const w of writes) await expect(w()).rejects.toThrow("demo mode: writes are disabled");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lets reads through in demo and writes through outside demo", async () => {
    window.history.replaceState(null, "", "/?demo=1");
    await apiFetch("/api/settings");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    window.history.replaceState(null, "", "/settings");
    await api.patchSettings({ enabled: false });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
