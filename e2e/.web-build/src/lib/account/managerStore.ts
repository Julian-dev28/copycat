/**
 * Which wallet-manager view is open, as a tiny external store so the nav
 * chip, the Account page and empty states can all open it without a
 * provider in the root layout. Read with useSyncExternalStore.
 */

export type ManagerView =
  | { view: "closed" }
  | { view: "list" }
  | { view: "create" }
  | { view: "connect"; tab?: "sign" | "key"; refresh?: { label: string; address: string } }
  | { view: "refresh"; accountId: string };

let current: ManagerView = { view: "closed" };
const listeners = new Set<() => void>();

export function getManagerView(): ManagerView {
  return current;
}

export function setManagerView(next: ManagerView): void {
  current = next;
  listeners.forEach((l) => l());
}

export function subscribeManager(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export const openWalletManager = (v: Exclude<ManagerView, { view: "closed" }> = { view: "list" }) => setManagerView(v);
export const closeWalletManager = () => setManagerView({ view: "closed" });
