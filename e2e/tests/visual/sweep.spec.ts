import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { test, expect, gotoDemo } from "../../fixtures";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * The "underwhelm sweep" (docs/qa/underwhelm_2026-10-14.md): walks every page
 * and state on a throwaway stack, screenshotting each so an agent can read
 * them with Read (Playwright screenshot -> image). Not a CI gate: a tool,
 * skipped unless E2E_SWEEP=1. Run it with:
 *   E2E_SWEEP=1 npx playwright test --project=visual -g sweep
 * For the full-stack-only scenarios (fresh install, no demo fixtures):
 *   E2E_STACK=full E2E_SWEEP=1 npx playwright test --project=visual -g sweep
 *
 * /discover is skipped: it is being removed in this QA round (another
 * agent's branch). Every other route gets desktop (1440x900) and phone
 * (390x844), dark and light, in demo mode's empty/populated states.
 */
test.skip(process.env.E2E_SWEEP !== "1", "visual sweep tool: set E2E_SWEEP=1 to run it");

const OUT = path.resolve(__dirname, "../../artifacts/sweep");
fs.mkdirSync(OUT, { recursive: true });

const WIDTHS = [
  { tag: "1440", width: 1440, height: 900 },
  { tag: "390", width: 390, height: 844 },
] as const;
const THEMES = ["dark", "light"] as const;

/** next-themes reads this key (attribute="class", no system theme) before first paint. */
async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((t) => {
    window.localStorage.setItem("theme", t);
  }, theme);
}

/**
 * Below-the-fold [data-reveal] content (components/shell/Reveal.tsx) only
 * turns visible once IntersectionObserver sees it actually cross into the
 * viewport on a real scroll. A `fullPage` screenshot resizes the viewport to
 * the full scroll height for one capture; it does not scroll there first, so
 * anything that mounted below the first screen gets captured mid-fade at
 * opacity 0 (found this way: a 36-row Scout board screenshotted as 3 cards
 * then a wall of blank space, everything past the fold invisible but still
 * laid out). Reveal.tsx skips the whole hidden-until-scrolled behavior under
 * reduced motion ("without JS, or under reduced motion, nothing is ever
 * hidden"), so emulating it is the correct fix, not a workaround: every
 * scenario below calls this before its first navigation.
 */
async function noRevealAnimations(page: Page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
}

/**
 * Under 1024px the Ticket (Trade page) is a closed bottom sheet
 * (Ticket.tsx `max-lg:hidden`); open it before filling its fields. No-op at
 * desktop width, where the toggle itself is `lg:hidden` and never mounts.
 * Waits for the toggle rather than a single isVisible() check: the Ticket
 * (and its toggle) mounts slightly after <main>, so a racy one-shot check
 * right after navigation reads "not there yet" and skips opening it.
 */
async function openTicketSheet(page: Page) {
  const vp = page.viewportSize();
  if (vp && vp.width >= 1024) return;
  const btn = page.getByRole("button", { name: "Show the ticket" });
  await btn.waitFor({ state: "visible", timeout: 15_000 });
  await btn.click();
}

async function shot(page: Page, name: string, fullPage = true) {
  // Let the reveal-on-mount fade (components/shell/Reveal.tsx) and any flash
  // tick settle so the screenshot shows the resting state, not a blend frame.
  await page.waitForTimeout(500);
  const vp = page.viewportSize();
  if (fullPage && vp && vp.width < 1024) {
    // BottomTabBar (.vt-tabbar, shell/BottomTabBar.tsx) is `fixed bottom-0`
    // below 640px; #ticket (Workspace.tsx) is `fixed bottom-0` below 1024px.
    // A fullPage capture resizes the viewport to the full scroll height for
    // one shot, and a fixed element keeps its on-screen offset from the
    // ORIGINAL (short) viewport instead of pinning to the new one's bottom:
    // it paints mid-page, over whatever content is actually there. Hiding
    // this pure-chrome pair for the capture only (every scenario that cares
    // what either one looks like takes its own non-fullPage shot instead,
    // see Scenario.mobileFullPage) avoids a misleading "ticket floats over
    // the Markets rail" screenshot that was never a real bug.
    await page.addStyleTag({ content: "#ticket, .vt-tabbar { display: none !important; }" });
  }
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage, animations: "disabled" });
}

interface Scenario {
  name: string;
  /** Navigates and waits for whatever marks the state "ready" to screenshot. */
  go: (page: Page) => Promise<void>;
  /**
   * false for a page with a `position: fixed` element below 1024px (the
   * Trade ticket's mobile bottom sheet, Workspace.tsx `max-lg:fixed
   * max-lg:bottom-0`): Chromium's fullPage capture resizes the viewport to
   * the full scroll height for one shot, and a fixed element keeps its
   * on-screen offset from the ORIGINAL viewport rather than pinning to the
   * bottom of the new, taller one -- it paints mid-page, overlapping
   * whatever content is actually there (found this way: the collapsed
   * ticket bar showed up floating over the Markets rail, see
   * docs/qa/underwhelm_2026-10-14.md's methodology note). A real phone
   * screen never has this problem: fixed means fixed to the one viewport a
   * phone actually has. A plain viewport screenshot matches that.
   */
  mobileFullPage?: boolean;
}

const SCENARIOS: Scenario[] = [
  { name: "trade-empty", mobileFullPage: false, go: async (p) => { await gotoDemo(p, "/"); await p.locator("main").waitFor(); } },
  {
    name: "trade-leverage-capped",
    mobileFullPage: false,
    go: async (p) => {
      // Default demo settings: max_position_leverage 50 == MAX_LEVERAGE_CAP, so
      // nothing ever caps until Settings lowers it below whatever the ticket asks for.
      await gotoDemo(p, "/settings");
      const maxLev = p.getByRole("slider", { name: "Maximum position leverage" });
      await maxLev.focus();
      await maxLev.press("Home"); // 1x: any later ticket leverage will exceed it
      // The patch is debounced 350ms (useDebouncedCallback) and cancelled on
      // unmount: navigating away sooner drops the change entirely.
      await p.waitForTimeout(600);
      await p.getByRole("link", { name: "Trade" }).click(); // client nav: the demo settings book is in-memory, a hard reload would drop it
      await p.locator("main").waitFor();
      await openTicketSheet(p);
      await p.getByRole("textbox", { name: /^Invest/ }).fill("250");
      await p.getByRole("radio", { name: "Set leverage" }).click();
      const slider = p.getByRole("slider", { name: /^Your leverage/ });
      await slider.focus();
      await slider.press("End");
      await expect(p.getByTestId("ticket-leverage-capped")).toBeVisible();
    },
  },
  {
    name: "trade-global-settings",
    mobileFullPage: false,
    go: async (p) => {
      await gotoDemo(p, "/");
      await openTicketSheet(p);
      await p.getByRole("radio", { name: "Use global" }).click();
      await expect(p.getByRole("link", { name: "Edit in Settings" })).toBeVisible();
    },
  },
  { name: "scout-board", go: async (p) => { await gotoDemo(p, "/scout"); await expect(p.locator("main article").first()).toBeVisible(); } },
  {
    name: "scout-trader-file",
    go: async (p) => {
      await gotoDemo(p, "/scout");
      const card = p.locator("main article").nth(1);
      await card.getByRole("link", { name: /open trader/i }).click();
      await expect(p.getByRole("heading", { name: "Performance" })).toBeVisible();
    },
  },
  {
    name: "scout-trader-file-strategy",
    go: async (p) => {
      await gotoDemo(p, "/scout");
      const card = p.locator("main article").nth(1);
      await card.getByRole("link", { name: /open trader/i }).click();
      await expect(p.getByRole("heading", { name: "Performance" })).toBeVisible();
      const sections = p.getByRole("tablist", { name: "Trader file sections" });
      await sections.getByRole("tab", { name: "Strategy" }).click();
      await expect(p.getByRole("tabpanel", { name: "Strategy" })).toBeVisible();
    },
  },
  { name: "portfolio-empty", go: async (p) => { await gotoDemo(p, "/portfolio"); await expect(p.getByRole("heading", { name: "Portfolio" })).toBeVisible(); } },
  {
    name: "portfolio-populated",
    go: async (p) => {
      await gotoDemo(p, "/");
      await openTicketSheet(p);
      await p.getByRole("textbox", { name: /^Invest/ }).fill("100");
      await p.getByRole("button", { name: "Copy trader" }).click();
      await expect(p.getByRole("tab", { name: /^Running \d+/ })).toHaveAccessibleName(/Running 1/);
      await p.getByRole("link", { name: "Portfolio" }).click();
      await p.locator("main").waitFor();
      await expect(p.getByRole("heading", { name: "Portfolio" })).toBeVisible();
    },
  },
  { name: "account-default", go: async (p) => { await gotoDemo(p, "/account"); await expect(p.getByRole("button", { name: "Accounts", exact: true })).toBeVisible(); } },
  { name: "settings", go: async (p) => { await gotoDemo(p, "/settings"); await expect(p.getByRole("heading", { name: "Settings" })).toBeVisible(); } },
];

for (const { tag, width, height } of WIDTHS) {
  for (const theme of THEMES) {
    test.describe(`sweep ${tag}px/${theme}`, () => {
      for (const sc of SCENARIOS) {
        test(`${sc.name}`, async ({ page }) => {
          await setTheme(page, theme);
          await noRevealAnimations(page);
          await page.setViewportSize({ width, height });
          await sc.go(page);
          const fullPage = width >= 1024 || sc.mobileFullPage !== false;
          await shot(page, `${sc.name}-${tag}-${theme}`, fullPage);
        });
      }
    });
  }
}

/** Keyboard-only pass: Tab through Trade and Scout, screenshotting focus rings. Desktop, dark, once. */
test.describe("sweep keyboard", () => {
  test("trade ticket: tab order reaches the primary action", async ({ page }) => {
    await setTheme(page, "dark");
    await noRevealAnimations(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoDemo(page, "/");
    await page.locator("main").waitFor();
    for (let i = 0; i < 6; i++) await page.keyboard.press("Tab");
    await shot(page, "trade-keyboard-tab6-1440-dark");
  });

  test("scout board: tab order reaches the sort control", async ({ page }) => {
    await setTheme(page, "dark");
    await noRevealAnimations(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoDemo(page, "/scout");
    await page.getByRole("combobox", { name: "Sort" }).focus();
    await shot(page, "scout-keyboard-sort-1440-dark");
  });
});

/**
 * Full-stack-only states demo fixtures never show: no trading account at
 * all. Requires E2E_STACK=full (a real throwaway api/engine/mock HL); skips
 * itself under the default web-only stack so the regular sweep run doesn't
 * need the heavier stack.
 */
test.describe("sweep full-stack: fresh install", () => {
  test("Account: no trading account yet", async ({ page, stack }) => {
    test.skip(stack.mode !== "full", "needs E2E_STACK=full");
    await noRevealAnimations(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    // Non-demo pages gate on the api bearer token (RequireToken); without it
    // every route just shows the "Enter your API token" panel.
    await page.addInitScript((t) => window.localStorage.setItem("copycat.apiToken", t), stack.token ?? "");
    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Set up a trading account" })).toBeVisible({ timeout: 20_000 });
    await shot(page, "account-no-wallet-1440-dark");
  });

  test("Trade: no trading account yet", async ({ page, stack }) => {
    test.skip(stack.mode !== "full", "needs E2E_STACK=full");
    await noRevealAnimations(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => window.localStorage.setItem("copycat.apiToken", t), stack.token ?? "");
    await page.goto("/");
    await page.locator("main").waitFor();
    await shot(page, "trade-no-wallet-1440-dark");
  });
});
