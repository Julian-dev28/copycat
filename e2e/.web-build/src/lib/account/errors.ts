/**
 * Plain-words text for a failed account api call. Pure.
 *   404/405 -> "api too old"
 *   401 "invalid passphrase" -> a form error, not a token problem
 *   429 -> the secret-route rate limit (5/min, 30/h per route)
 */
import { ApiError } from "@/lib/api/client";
import { apiProblem, problemText } from "@/lib/trade/apiState";
import { INVALID_PASSPHRASE } from "./secretFetch";

export function accountErrorText(err: unknown, what = "accounts"): string {
  if (!err) return "";
  if (err instanceof ApiError) {
    if (err.status === 401 && err.message === INVALID_PASSPHRASE) return "Wrong passphrase. Nothing was signed.";
    if (err.status === 429) return "Too many attempts. copycat allows 5 key operations a minute and 30 an hour. Wait a minute, then retry.";
  }
  if (apiProblem(err) === "too_old") return `api too old: your api has no ${what} route yet. Update services/api and restart it.`;
  return problemText(err, what);
}

export function isTooOld(err: unknown): boolean {
  return apiProblem(err) === "too_old";
}

/** POST .../activate refused because the current account still has engine copies open. */
export function isOpenCopiesConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}
