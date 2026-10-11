/**
 * Bearer token storage. Entered once in the Settings drawer, kept in
 * localStorage only (never sent anywhere but the configured api base URL).
 * All access goes through try/catch: localStorage can throw (private
 * browsing, blocked storage) and this must never crash the app.
 */

const STORAGE_KEY = "copycat.apiToken";
const listeners = new Set<() => void>();

/** For useSyncExternalStore: fires on our own writes and on other tabs' writes. */
export function subscribeToken(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY) listener();
  };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

function notify(): void {
  listeners.forEach((l) => l());
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, token.trim());
  } catch {
    // ignore: storage unavailable, token just won't persist across reloads
  }
  notify();
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  notify();
}
