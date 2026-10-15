/**
 * Contract v8 wallet lifecycle for "Your wallets": Running | Stopped |
 * Archived tabs, the status badge, and which row actions each status gets.
 * Pure, unit-tested.
 *
 *   running  -> Pause, Adjust, Stop, Log, Share
 *   paused   -> Resume, Adjust, Stop, Log, Share  (no new copies; exits still followed)
 *   stopping -> Log, Share                        (closing or running out)
 *   stopped  -> Copy again, Archive, Log, Share
 *   archived -> Log, Share                        (hidden from the other tabs)
 */
import type { WalletPosition, WalletStatus } from "./types";

export type LifecycleTab = "running" | "stopped" | "archived";
export const LIFECYCLE_TABS: { id: LifecycleTab; label: string }[] = [
  { id: "running", label: "Running" },
  { id: "stopped", label: "Stopped" },
  { id: "archived", label: "Archived" },
];

export type RowAction = "pause" | "resume" | "adjust" | "stop" | "archive" | "log" | "share";

/** The status, from the api (v8) or derived from the v4-v7 fields. */
export function walletStatus(w: Pick<WalletPosition, "status" | "stopping" | "in_book" | "open_copies" | "archived_ms">): WalletStatus {
  if (w.status) return w.status;
  if (w.archived_ms) return "archived";
  if (w.stopping) return "stopping";
  // Out of the book: still winding down while copies are open, else done.
  if (w.in_book === false) return w.open_copies > 0 ? "stopping" : "stopped";
  return "running";
}

export function tabOf(status: WalletStatus): LifecycleTab {
  if (status === "archived") return "archived";
  if (status === "stopping" || status === "stopped") return "stopped";
  return "running";
}

export function tabCounts(wallets: WalletPosition[]): Record<LifecycleTab, number> {
  const out: Record<LifecycleTab, number> = { running: 0, stopped: 0, archived: 0 };
  for (const w of wallets) out[tabOf(walletStatus(w))] += 1;
  return out;
}

export function inTab(wallets: WalletPosition[], tab: LifecycleTab): WalletPosition[] {
  return wallets.filter((w) => tabOf(walletStatus(w)) === tab);
}

export function rowActions(status: WalletStatus): RowAction[] {
  switch (status) {
    case "running":
      return ["pause", "adjust", "stop", "log", "share"];
    case "paused":
      return ["resume", "adjust", "stop", "log", "share"];
    case "stopping":
      return ["log", "share"];
    case "stopped":
      return ["adjust", "archive", "log", "share"];
    case "archived":
      return ["log", "share"];
  }
}

export const STATUS_BADGE: Record<WalletStatus, { label: string; tone: "success" | "neutral" | "warning" | "danger" | "accent"; hint: string }> = {
  running: { label: "running", tone: "success", hint: "Copying every open, add, reduce and close." },
  paused: { label: "paused", tone: "neutral", hint: "No new copies; exits still followed." },
  stopping: { label: "stopping", tone: "warning", hint: "Opening nothing new; open copies are closing or following them out." },
  stopped: { label: "stopped", tone: "neutral", hint: "Done: no open copies. Archive it to tidy the list." },
  archived: { label: "archived", tone: "neutral", hint: "Kept for its history and PnL." },
};

/** The word to type to confirm archiving. */
export const ARCHIVE_WORD = "archive";

export function archiveConfirmed(typed: string): boolean {
  return typed.trim().toLowerCase() === ARCHIVE_WORD;
}

/** Plain-words result line after an action. */
export function actionDone(action: "pause" | "resume" | "archive", name: string): string {
  if (action === "pause") return `Paused ${name}: no new copies; exits still followed.`;
  if (action === "resume") return `Resumed ${name}: copying their new positions again.`;
  return `Archived ${name}. It lives under Archived now.`;
}
