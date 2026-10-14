/**
 * Helpers for the full lane (`npm run full`, E2E_STACK=full): the real api, engine and
 * Scout on a temp data dir against the mock Hyperliquid (e2e/mock_hl/server.py). Nothing
 * here can reach the operator's stack: the harness refuses :3000 / :8787 / ./data.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import type { StackState } from "../../harness/stack";

/** The mock leaderboard (e2e/mock_hl/server.py LEADERS). Made-up addresses, never real wallets. */
export const ALPHA = "0x1111111111111111111111111111111111111111";
export const BETA = "0x2222222222222222222222222222222222222222";
export const GAMMA = "0x3333333333333333333333333333333333333333";

/** Put the stack's bearer token where the web reads it (lib/api/token.ts) before any page script runs. */
export async function signIn(page: Page, st: StackState): Promise<void> {
  await page.addInitScript((t: string) => {
    try { localStorage.setItem("copycat.apiToken", t); } catch { /* storage blocked: the test then sees the token gate */ }
  }, st.token!);
}

/** The mock's control plane (GET without a body, POST with one). */
export async function mock(req: APIRequestContext, st: StackState, path: string, body?: unknown): Promise<any> {
  const r = body === undefined ? await req.get(st.mockURL! + path) : await req.post(st.mockURL! + path, { data: body });
  if (!r.ok()) throw new Error(`mock ${path}: HTTP ${r.status()} ${await r.text()}`);
  return r.json();
}

/** The copycat api with the stack token. */
export async function api(req: APIRequestContext, st: StackState, path: string,
                          init: { method?: "GET" | "POST" | "PUT" | "PATCH"; data?: unknown } = {}): Promise<any> {
  const r = await req.fetch(st.apiURL + path, {
    method: init.method ?? "GET", data: init.data, headers: { Authorization: `Bearer ${st.token}` },
  });
  if (!r.ok()) throw new Error(`api ${init.method ?? "GET"} ${path}: HTTP ${r.status()} ${await r.text()}`);
  return r.json();
}

/** Queue a full Scout refresh and wait until a pass that STARTED after this call finished. */
export async function refreshScout(req: APIRequestContext, st: StackState, timeoutMs = 90_000): Promise<void> {
  const t0 = Date.now();
  await api(req, st, "/api/scout/refresh", { method: "POST" });
  await expect.poll(async () => {
    const s = await api(req, st, "/api/scout/status");
    return s.state === "idle" && (s.last_ok_ms ?? 0) >= t0 ? "done" : `${s.state} ${s.stage ?? ""} ${s.done}/${s.total}`;
  }, { message: "scout refresh after the seed", timeout: timeoutMs, intervals: [500, 1000] }).toBe("done");
}

/** Decoded orders the mock received for `user` (our main account), oldest first. */
export async function ordersFor(req: APIRequestContext, st: StackState, user: string): Promise<any[]> {
  const recs: any[] = await mock(req, st, "/__mock/exchange");
  return recs.filter((r) => r.type === "order" && r.user === user.toLowerCase()).flatMap((r) => r.orders ?? []);
}
