import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect, gotoDemo } from "../../fixtures";

/**
 * Scout a11y gate: the board and the trader file, every axe rule including
 * color-contrast. The QA swarm had to exclude color-contrast here because
 * dark --muted (#8d8d96) sat at 4.46:1 on --warn-soft, a few hundredths under
 * AA; the token is now #96969f (tokens.test.ts pins it and checks every
 * tinted well), so nothing is excluded any more.
 *
 * The reveal-on-mount fade (components/shell/Reveal.tsx, 0.45s) blends text
 * toward its background mid-transition and axe reports a false contrast hit
 * on the still-fading node, so every scan waits for it to settle first.
 */
async function scan(page: Page, include = "main") {
  await page.waitForTimeout(600);
  const results = await new AxeBuilder({ page }).include(include).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

async function openSecondTraderFile(page: Page): Promise<void> {
  await gotoDemo(page, "/scout");
  const cards = page.locator("main article");
  await expect(cards.first()).toBeVisible();
  await cards.nth(1).getByRole("link", { name: /open trader/i }).click();
  await expect(page).toHaveURL(/\/scout\/0x[0-9a-f]{40}\?demo=1/);
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
}

test.describe("Scout a11y (/scout?demo=1)", () => {
  test("no automatic accessibility violations on the board", async ({ page }) => {
    await gotoDemo(page, "/scout");
    await expect(page.locator("main article").first()).toBeVisible();
    await scan(page);
  });

  test("no violations on the trader file: Positions, Round trips, Fills, Open orders, Strategy", async ({ page }) => {
    await openSecondTraderFile(page);
    await scan(page);
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    for (const name of ["Round trips", "Fills", "Open orders", "Strategy"]) {
      await sections.getByRole("tab", { name }).click();
      await expect(sections.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
      await scan(page);
    }
  });

  test("keyboard: the file's wide tables are focusable scroll regions", async ({ page }) => {
    // A bare overflow-x-auto div is not in the tab order, so a keyboard user
    // could never scroll the 11-column round-trips table sideways. Each one
    // is a labelled region with tabIndex 0 (components/ui/Table.tsx).
    await openSecondTraderFile(page);
    // Positions is the default tab; its table and the calendar are regions too.
    await expect(page.getByRole("region", { name: "Open positions" })).toHaveAttribute("tabindex", "0");
    await expect(page.getByRole("region", { name: "Daily PnL calendar" })).toHaveAttribute("tabindex", "0");
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Round trips" }).click();
    const region = page.getByRole("region", { name: "Round trips" });
    await expect(region).toBeVisible();
    await expect(region).toHaveAttribute("tabindex", "0");
    await region.focus();
    await expect(region).toBeFocused();
  });

  test("390px width: no horizontal overflow, controls still reachable", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoDemo(page, "/scout");
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, "page must not scroll horizontally at 390px").toBeLessThanOrEqual(clientWidth + 1);
    await expect(page.getByRole("combobox", { name: "Sort" })).toBeVisible();
  });

  test("390px width: the trader file does not scroll the page sideways either", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openSecondTraderFile(page);
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Round trips" }).click();
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, "wide tables scroll inside their region, not the page").toBeLessThanOrEqual(clientWidth + 1);
  });

  test("keyboard: Tab reaches the sort control and a card's primary action", async ({ page }) => {
    await gotoDemo(page, "/scout");
    const sort = page.getByRole("combobox", { name: "Sort" });
    await sort.focus();
    await expect(sort).toBeFocused();
    let guard = 0;
    let found = false;
    while (guard++ < 80) {
      await page.keyboard.press("Tab");
      const label = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        return el ? (el.getAttribute("aria-label") || el.textContent || "") : "";
      });
      if (/add to copies|already copying|copying/i.test(label)) {
        found = true;
        break;
      }
    }
    expect(found, "a card's copy action should be reachable by keyboard alone").toBe(true);
  });
});
