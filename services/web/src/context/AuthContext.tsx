"use client";

/**
 * Bearer token state for the whole app. The token lives in localStorage
 * (see lib/api/token.ts); this context is just the reactive layer on top
 * so components re-render when it changes, and the single place that
 * reacts to a 401 from anywhere in the app by dropping into the
 * "enter your token" state (see components/SettingsDrawer.tsx).
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode,
} from "react";
import { onUnauthorized } from "@/lib/api/client";
import { clearStoredToken, getStoredToken, setStoredToken, subscribeToken } from "@/lib/api/token";

interface AuthContextValue {
  token: string | null;
  /** True once we've seen a 401 since the token was last set — show the "enter your token" state. */
  unauthorized: boolean;
  hasToken: boolean;
  setToken: (token: string) => void;
  clearToken: () => void;
  /** Settings drawer open/close, lifted here so any "enter your token" prompt can open it. */
  drawerOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const noSubscribe = () => () => {};
const isDemoUrl = () => new URLSearchParams(window.location.search).get("demo") === "1";

export function AuthProvider({ children }: { children: ReactNode }) {
  // undefined on the server and during hydration, then the stored value.
  const token = useSyncExternalStore<string | null | undefined>(
    subscribeToken, getStoredToken, () => undefined,
  );
  const [unauthorized, setUnauthorized] = useState(false);
  // null = the user hasn't opened or closed it yet: open it when there is no token.
  const [drawerChoice, setDrawerChoice] = useState<boolean | null>(null);
  // `?demo=1` pages (Scout's fixture board) need no token, so don't pop the drawer over them.
  // Read at render time; the snapshot is recomputed on every render, so client navigation is picked up.
  const demo = useSyncExternalStore(noSubscribe, isDemoUrl, () => false);
  const drawerOpen = drawerChoice ?? (token === null && !demo);

  useEffect(() => {
    return onUnauthorized(() => {
      setUnauthorized(true);
      setDrawerChoice(true);
    });
  }, []);

  const setToken = useCallback((next: string) => {
    setStoredToken(next);
    setUnauthorized(false);
  }, []);

  const clearToken = useCallback(() => {
    clearStoredToken();
    setUnauthorized(false);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token: token ?? null,
      unauthorized,
      hasToken: Boolean(token),
      setToken,
      clearToken,
      drawerOpen,
      openDrawer: () => setDrawerChoice(true),
      closeDrawer: () => setDrawerChoice(false),
    }),
    [token, unauthorized, setToken, clearToken, drawerOpen],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
