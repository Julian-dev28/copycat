/**
 * fetch for the passphrase routes (refresh-agent, transfer). The shared
 * apiFetch treats every 401 as "your api token was rejected" and drops the
 * whole app into the token prompt; on these routes a 401 usually means
 * "invalid passphrase", which must stay a form error. So:
 *   - 401 "invalid passphrase" -> ApiError(401), no global sign-out
 *   - any other 401            -> re-checked through apiFetch on a GET (so the
 *                                 token prompt still appears), never resending
 *                                 the secret body
 * Everything else matches apiFetch (base URL, bearer token, error detail, the
 * demo write guard).
 */
import { ApiError, DemoWriteError, apiFetch, getApiBase, isDemoMode } from "@/lib/api/client";
import { getStoredToken } from "@/lib/api/token";

export const INVALID_PASSPHRASE = "invalid passphrase";

async function detailOf(res: Response): Promise<{ detail: string | null; body: unknown }> {
  try {
    const body: unknown = await res.json();
    const d = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
    return { detail: typeof d === "string" ? d : d === null ? null : JSON.stringify(d), body };
  } catch {
    return { detail: null, body: undefined };
  }
}

export async function secretFetch<T>(path: string, body: unknown, fetchImpl: typeof fetch = fetch): Promise<T> {
  // Every route here is a write: the demo guard applies like in apiFetch (UX audit #1).
  if (isDemoMode()) throw new DemoWriteError();
  const headers = new Headers({ Accept: "application/json", "Content-Type": "application/json" });
  const token = getStoredToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetchImpl(`${getApiBase()}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, `can't reach the api at ${getApiBase()}. Is it running?`);
  }
  if (res.ok) {
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }
  const { detail, body: errBody } = await detailOf(res);
  if (res.status === 401 && detail !== INVALID_PASSPHRASE) {
    // a real token problem: let apiFetch's 401 path raise the token prompt
    await apiFetch("/api/settings").catch(() => undefined);
  }
  throw new ApiError(res.status, detail ?? `${res.status} ${res.statusText}`, errBody);
}
