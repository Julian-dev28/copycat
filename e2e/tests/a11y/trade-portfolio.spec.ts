/**
 * Axe scan of this agent's two pages (Trade, Portfolio), per the QA brief's
 * "axe a11y clean on / and /portfolio". Scout/Settings/Account/Discover are
 * owned by other sessions; add their own files here rather than extend this
 * one, so two sessions never edit the same spec.
 *
 * Demo mode, so no api/engine is needed and no real data drifts the result.
 * wcag2a/wcag2aa/wcag21aa/best-practice mirror axe's own default ruleset
 * (`AxeBuilder` with no `.withTags()` already runs these; listed explicitly
 * so a future axe-core upgrade changing its defaults doesn't silently widen
 * or narrow what this gate checks).
 */
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect, gotoDemo } from "../../fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"];

/**
 * Newly-mounted sections fade in over `--dur-base` (220ms, globals.css) via
 * the reveal-on-mount system (`components/shell/Reveal.tsx`). Scanning mid
 * fade blends a badge's foreground toward its background and axe reports a
 * real-looking but false color-contrast violation on the still-transitioning
 * element. Settle past it before every scan.
 */
async function settled(page: Page): Promise<AxeBuilder> {
  await page.waitForTimeout(400);
  return new AxeBuilder({ page }).withTags(TAGS);
}

test.describe("a11y: Trade and Portfolio", () => {
  test.afterEach(async ({ errors }) => {
    expect(errors, "no uncaught page error during the scan").toEqual([]);
  });

  test("/ (Trade): no wallet selected", async ({ page }) => {
    await gotoDemo(page, "/");
    const results = await (await settled(page)).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("/ (Trade): custom ticket open with an amount, leverage slider and coin filters filled in", async ({ page }) => {
    await gotoDemo(page, "/");
    await page.getByRole("textbox", { name: /^Invest/ }).fill("250");
    await page.getByRole("radio", { name: "Set leverage" }).click();
    const only = page.getByRole("combobox", { name: "Only these coins" });
    await only.click();
    await only.fill("BTC");
    await only.press("Enter");
    const results = await (await settled(page)).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("/portfolio: empty book", async ({ page }) => {
    await gotoDemo(page, "/portfolio");
    const results = await (await settled(page)).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("/portfolio: with a running copy (positions table, Your wallets populated)", async ({ page }) => {
    await gotoDemo(page, "/");
    await page.getByRole("textbox", { name: /^Invest/ }).fill("100");
    await page.getByRole("button", { name: "Copy trader" }).click();
    await expect(page.getByRole("tab", { name: /^Running \d+/ })).toHaveAccessibleName(/Running 1/);
    // A client-side nav, not another gotoDemo: the in-memory demo book lives
    // in this page's JS context and a hard reload drops it (a known, already
    // flagged low-severity demo gap), which would leave Portfolio empty and
    // defeat the point of this scan.
    await page.getByRole("link", { name: "Portfolio" }).click();
    await page.locator("main").waitFor();
    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
    const results = await (await settled(page)).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });
});
