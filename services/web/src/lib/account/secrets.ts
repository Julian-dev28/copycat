/**
 * Handling for the few secrets the browser touches (a created wallet's
 * private key, shown once). Rules: no localStorage, no query cache, no
 * console, and the clipboard is wiped after a minute where the browser lets
 * us.
 */

export const CLIPBOARD_CLEAR_MS = 60_000;

export interface ClipboardLike {
  writeText(text: string): Promise<void>;
  readText?(): Promise<string>;
}

/**
 * Copy `text`, then after `ms` clear the clipboard if it still holds it.
 * When the browser will not let us read the clipboard (most do not without
 * a permission prompt), we clear it anyway: a stale private key on the
 * clipboard is worse than losing something copied in the last minute.
 * Returns a cancel function (call it on unmount to skip the clear).
 */
export async function copySecret(
  text: string,
  clipboard: ClipboardLike | undefined = typeof navigator !== "undefined" ? navigator.clipboard : undefined,
  ms = CLIPBOARD_CLEAR_MS,
  schedule: (fn: () => void, ms: number) => () => void = (fn, d) => {
    const t = setTimeout(fn, d);
    return () => clearTimeout(t);
  },
): Promise<() => void> {
  if (!clipboard) throw new Error("Clipboard is not available here. Select the key and copy it by hand.");
  await clipboard.writeText(text);
  return schedule(() => {
    void clearIfStill(text, clipboard);
  }, ms);
}

export async function clearIfStill(text: string, clipboard: ClipboardLike): Promise<boolean> {
  try {
    if (clipboard.readText) {
      const now = await clipboard.readText();
      if (now !== text) return false;
    }
  } catch {
    // read blocked: fall through and clear
  }
  try {
    await clipboard.writeText("");
    return true;
  } catch {
    // the tab lost focus: browsers refuse clipboard writes from background tabs
    return false;
  }
}

/** The backup file's contents. Plain text, so it opens anywhere. */
export function backupText(opts: { label: string; address: string; privateKey: string; warning: string; nowMs: number }): string {
  return [
    "copycat wallet backup",
    "=====================",
    "",
    `Name:        ${opts.label}`,
    `Address:     ${opts.address}`,
    `Created:     ${new Date(opts.nowMs).toISOString()}`,
    "",
    "Private key (anyone with this controls the wallet and its funds):",
    opts.privateKey,
    "",
    opts.warning,
    "",
    "Keep this file offline. Do not email it, paste it in chat, or store it in cloud notes.",
    "You can import this key into any EVM wallet (MetaMask, Rabby) to reach the funds without copycat.",
    "",
  ].join("\n");
}

export function backupFilename(label: string, address: string): string {
  const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "wallet";
  return `copycat-backup-${slug}-${address.toLowerCase().slice(2, 8)}.txt`;
}

/** Hand the text to the browser as a download; the object URL is revoked right after. */
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
