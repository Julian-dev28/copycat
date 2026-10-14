/**
 * Shared fixtures. `baseURL` is the throwaway web server global-setup started.
 * Demo-mode pages get a write guard: every non-GET request that leaves the page
 * (to anything, not only the api) is recorded and fails the test at teardown.
 * `errors` is the same shape for uncaught page errors (hydration crashes,
 * render throws, a native call made with the wrong receiver e.g. a bare
 * `setTimeout` reference invoked as `obj.method()`, which jsdom tolerates
 * but a real browser's brand check does not: found this way in toastStore.ts).
 */
import { test as base, expect, type Page, type Request } from "@playwright/test";
import { readState, type StackState } from "./harness/stack";

export interface Fixtures {
  stack: StackState;
  writes: string[];
  errors: string[];
}

export const test = base.extend<Fixtures>({
  stack: async ({}, use) => {
    await use(readState());
  },
  baseURL: async ({}, use) => {
    await use(readState().webURL);
  },
  writes: async ({ page }, use) => {
    const writes: string[] = [];
    const onReq = (r: Request) => {
      const m = r.method();
      if (m !== "GET" && m !== "HEAD" && m !== "OPTIONS") writes.push(`${m} ${r.url()}`);
    };
    page.on("request", onReq);
    await use(writes);
    page.off("request", onReq);
  },
  errors: async ({ page }, use) => {
    const errors: string[] = [];
    const onErr = (e: Error) => errors.push(String(e));
    page.on("pageerror", onErr);
    await use(errors);
    page.off("pageerror", onErr);
  },
});

export { expect };

/** Every page the app has. Dynamic ones use a demo address. */
export const DEMO_TRADER = "0x1111111111111111111111111111111111111111";
export const ROUTES = ["/", "/scout", "/portfolio", "/account", "/settings"] as const;

/** Go to a page in demo mode and wait for the client to hydrate. */
export async function gotoDemo(page: Page, route: string, extra = ""): Promise<void> {
  const sep = route.includes("?") ? "&" : "?";
  await page.goto(`${route}${sep}demo=1${extra}`);
  await page.locator("main").waitFor();
}

/** Collect uncaught page errors (hydration crashes, render throws). Prefer the `errors` fixture in new tests: it is torn down for you and easy to assert on in one `afterEach`. */
export function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}
