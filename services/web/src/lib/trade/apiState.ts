/**
 * Plain-words state for a failed Trade api call, and the legacy route
 * redirects. Pure, unit-tested.
 */
import { ApiError } from "@/lib/api/client";

export type ApiProblem = "too_old" | "unavailable" | "unauthorized" | "unreachable" | "rejected" | "error";

export function apiProblem(err: unknown): ApiProblem | null {
  if (!err) return null;
  if (!(err instanceof ApiError)) return "error";
  if (err.status === 0) return "unreachable";
  if (err.status === 401) return "unauthorized";
  if (err.status === 404 || err.status === 405) return "too_old";
  if (err.status === 503) return "unavailable";
  if (err.status === 409 || err.status === 422 || err.status === 400) return "rejected";
  return "error";
}

export function problemText(err: unknown, what: string): string {
  const p = apiProblem(err);
  const msg = err instanceof Error ? err.message : "";
  switch (p) {
    case null:
      return "";
    case "too_old":
      return `Your api has no ${what} route yet. Update services/api and restart it.`;
    case "unavailable":
      return `The api is up but ${what} is unavailable right now (503). The engine or discovery service may be starting.`;
    case "unauthorized":
      return "The api rejected your token (401). Paste the current one in the token drawer.";
    case "unreachable":
      return msg || "Can't reach the api. Is it running?";
    case "rejected":
      return `The api refused it: ${msg}`;
    default:
      return msg || "Something went wrong.";
  }
}

/** Old routes and where they live now. Query strings (?demo=1, ?w=) are carried over. */
export const LEGACY_ROUTES: Record<string, string> = {
  "/copy": "/settings",
  "/positions": "/portfolio",
  "/trade": "/",
};

type SearchParamsLike = Record<string, string | string[] | undefined>;

export function legacyRedirect(path: string, sp: SearchParamsLike = {}): string {
  const target = LEGACY_ROUTES[path] ?? path;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (v === undefined) continue;
    for (const one of Array.isArray(v) ? v : [v]) q.append(k, one);
  }
  const qs = q.toString();
  return qs ? `${target}?${qs}` : target;
}
