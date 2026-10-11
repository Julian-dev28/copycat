/**
 * Which screen the trader file shows. Pure, so the branching is tested.
 *
 * 404 is ambiguous: the scout route answers 404 for an address it rejects,
 * and an api build without the route answers FastAPI's bare "Not Found".
 * The address is validated client-side first, so a 404 for a valid address
 * with the bare detail means the api is too old; any other 404 is "not found".
 */
import { ApiError } from "@/lib/api/client";
import { isValidAddress } from "@/lib/address";
import type { ProfileResult } from "../api";

export type FileView = "invalid" | "loading" | "building" | "ready" | "not_found" | "too_old" | "error";

export function fileView(address: string, data: ProfileResult | undefined, error: unknown): FileView {
  if (!isValidAddress(address)) return "invalid";
  if (data?.kind === "ready") return "ready";
  if (data?.kind === "building") return "building";
  if (error instanceof ApiError) {
    if (error.status === 405) return "too_old";
    if (error.status === 404) return error.message === "Not Found" ? "too_old" : "not_found";
  }
  if (error) return "error";
  return "loading";
}

/** "Stage 2 of 3, 40/280, about 3 min" for the building screen. */
export function buildingText(s: { stage?: string | null; done: number; total: number; eta_s?: number | null }): string {
  const parts: string[] = [];
  if (s.stage) parts.push(`stage: ${s.stage}`);
  if (s.total > 0) parts.push(`${s.done}/${s.total}`);
  if (s.eta_s && s.eta_s > 0) parts.push(s.eta_s < 90 ? `about ${Math.round(s.eta_s)}s` : `about ${Math.round(s.eta_s / 60)} min`);
  return parts.join(" · ");
}
