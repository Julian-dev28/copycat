/**
 * Version-skew banner text (audit M12). GET /api/health lists the processes
 * running older code than what is on disk for them (`stale`, each process
 * against the packages it imports); after a pull, the api's preview, what-if
 * and MCP plans would otherwise silently disagree with the engine.
 */
import type { HealthResponse } from "@/lib/api/types";
import { CONTRACT_VERSION } from "@/lib/api/types";

const NAMES: Record<string, string> = { api: "api", engine: "engine", scout: "scout" };

/** null when everything runs the same code. The engine trades, so it is named first. */
export function staleBuildText(h: Pick<HealthResponse, "stale" | "contract_version"> | undefined): string | null {
  if (!h) return null;
  // the engine trades, so it is named first; the api next (it is what the page talks to)
  const rank = (s: string) => (s === "engine" ? 0 : s === "api" ? 1 : 2);
  const stale = [...(h.stale ?? [])].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const webOld = h.contract_version > CONTRACT_VERSION;
  if (stale.length === 0 && !webOld) return null;
  const parts: string[] = [];
  if (stale.length) {
    const who = stale.map((s) => NAMES[s] ?? s).join(" and ");
    parts.push(`The ${who} ${stale.length > 1 ? "are" : "is"} running older code than the code on disk. Restart ${stale.length > 1 ? "them" : "it"} so previews match what the engine does.`);
  }
  if (webOld) parts.push("This page is older than the api. Reload it.");
  return parts.join(" ");
}
