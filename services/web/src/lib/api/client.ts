/**
 * The only way services/web talks to the network: HTTP to services/api,
 * base URL from NEXT_PUBLIC_COPYCAT_API (default http://localhost:8787).
 * Every call attaches the bearer token from localStorage (see token.ts)
 * unless one is passed explicitly, and every 401 notifies subscribers
 * (the TokenProvider) so the app can drop into the "enter your token"
 * state instead of failing silently per-call.
 */
import type {
  DiscoveryRun,
  EngineEvent,
  EngineStatus,
  HealthResponse,
  Settings,
  SettingsPatch,
  StartDiscoveryRunBody,
} from "./types";
import { getStoredToken } from "./token";

export class ApiError extends Error {
  readonly status: number;
  readonly body?: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type Unsubscribe = () => void;
const unauthorizedListeners = new Set<() => void>();

/** Subscribe to 401 responses from any apiFetch call. Returns an unsubscribe fn. */
export function onUnauthorized(cb: () => void): Unsubscribe {
  unauthorizedListeners.add(cb);
  return () => unauthorizedListeners.delete(cb);
}

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_COPYCAT_API?.replace(/\/+$/, "") || "http://localhost:8787";
}

export interface ApiFetchOptions extends RequestInit {
  /** Override the stored token for this call (tests, or an explicit re-auth flow). */
  token?: string | null;
}

/**
 * Low-level fetch wrapper. Exported so tests can exercise header/401/body
 * behavior directly; the typed endpoint functions below are the normal
 * call surface for components.
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { token, headers: initHeaders, body, ...rest } = options;
  const headers = new Headers(initHeaders);
  headers.set("Accept", "application/json");
  if (body !== undefined && !(body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const effectiveToken = token === undefined ? getStoredToken() : token;
  if (effectiveToken) {
    headers.set("Authorization", `Bearer ${effectiveToken}`);
  }

  let res: Response;
  try {
    res = await fetch(`${getApiBase()}${path}`, { ...rest, body, headers });
  } catch (err) {
    // fetch only rejects on network failure (api down, wrong host, CORS):
    // status 0 so callers can tell "unreachable" apart from an http error.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, `can't reach the api at ${getApiBase()}. Is it running?`);
  }

  if (res.status === 401) {
    unauthorizedListeners.forEach((cb) => cb());
    let detail = "unauthorized: enter your API token";
    try {
      const parsed = await res.json();
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        detail = String((parsed as { detail: unknown }).detail);
      }
    } catch {
      // body wasn't json; keep the default message
    }
    throw new ApiError(401, detail);
  }

  if (!res.ok) {
    let parsedBody: unknown;
    let message = `${res.status} ${res.statusText}`;
    try {
      parsedBody = await res.json();
      if (parsedBody && typeof parsedBody === "object" && "detail" in parsedBody) {
        message = String((parsedBody as { detail: unknown }).detail);
      }
    } catch {
      // not json, keep the status line as the message
    }
    throw new ApiError(res.status, message, parsedBody);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/** True when the api answered but doesn't have the route (an older api build). */
export function isNotSupported(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 405);
}

/** Whatever POST /api/engine/close-all returns; the ui only needs it to succeed. */
export type CloseAllResult = Record<string, unknown> | undefined;

function json(body: unknown): string {
  return JSON.stringify(body);
}

// ── typed endpoints, one per route in docs/ARCHITECTURE.md ──────────────────

export const api = {
  health: () => apiFetch<HealthResponse>("/api/health"),

  getSettings: () => apiFetch<Settings>("/api/settings"),

  putSettings: (settings: Settings) =>
    apiFetch<Settings>("/api/settings", { method: "PUT", body: json(settings) }),

  /** `leader_overrides` entries of `null` clear that leader's override. */
  patchSettings: (patch: SettingsPatch) =>
    apiFetch<Settings>("/api/settings", { method: "PATCH", body: json(patch) }),

  addLeader: (address: string) =>
    apiFetch<Settings>("/api/leaders", { method: "POST", body: json({ address }) }),

  removeLeader: (address: string) =>
    apiFetch<Settings>(`/api/leaders/${encodeURIComponent(address)}`, { method: "DELETE" }),

  getStatus: () => apiFetch<EngineStatus>("/api/status"),

  getEvents: (opts: { limit?: number; sinceMs?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.sinceMs !== undefined) params.set("since_ms", String(opts.sinceMs));
    const qs = params.toString();
    return apiFetch<EngineEvent[]>(`/api/events${qs ? `?${qs}` : ""}`);
  },

  /** Flips `enabled` false server-side and returns the updated Settings (not EngineStatus). */
  haltEngine: () => apiFetch<Settings>("/api/engine/halt", { method: "POST" }),

  /**
   * Market-closes every copy position copycat opened. 404/405 means this api
   * build predates the route: check with isNotSupported().
   */
  closeAllCopies: () => apiFetch<CloseAllResult>("/api/engine/close-all", { method: "POST" }),

  startDiscoveryRun: (body: StartDiscoveryRunBody) =>
    apiFetch<{ run_id: string }>("/api/discovery/runs", { method: "POST", body: json(body) }),

  getLatestDiscoveryRun: () => apiFetch<DiscoveryRun>("/api/discovery/runs/latest"),

  getDiscoveryRun: (runId: string) =>
    apiFetch<DiscoveryRun>(`/api/discovery/runs/${encodeURIComponent(runId)}`),
};
