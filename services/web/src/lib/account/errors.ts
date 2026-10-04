/** Plain-words text for a failed account api call. A 404/405 reads "api too old". */
import { apiProblem, problemText } from "@/lib/trade/apiState";

export function accountErrorText(err: unknown, what = "accounts"): string {
  if (!err) return "";
  if (apiProblem(err) === "too_old") return `api too old: your api has no ${what} route yet. Update services/api and restart it.`;
  return problemText(err, what);
}

export function isTooOld(err: unknown): boolean {
  return apiProblem(err) === "too_old";
}
