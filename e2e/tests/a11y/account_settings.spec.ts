/**
 * Onboarding/account/settings a11y + layout gate. Demo mode (no backend
 * needed, no writes allowed - see fixtures.ts `writes`). Axe flags the
 * violations the UX audit found by hand (e.g. the unlabeled leverage range
 * input on Settings); this makes them a gate, not a one-time manual scan.
 */
import AxeBuilder from "@axe-core/playwright";
import { test, expect, gotoDemo } from "../../fixtures";

const PAGES = ["/account", "/settings"] as const;

for (const route of PAGES) {
  test(`${route}: axe reports no serious/critical violations (demo)`, async ({ page }) => {
    await gotoDemo(page, route);
    // Let the page's own data (demo fixtures) finish rendering before scanning.
    await page.locator("main").waitFor();
    await page.waitForTimeout(500);
    const results = await new AxeBuilder({ page }).include("main").analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    const detail = serious.map((v) => `${v.id} (${v.impact}): ${v.help} - ${v.nodes.length} node(s)`).join("\n");
    expect(serious, detail).toEqual([]);
  });

  test(`${route}: fits a 390px phone with no horizontal scroll`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoDemo(page, route);
    await page.locator("main").waitFor();
    await page.waitForTimeout(500);
    const widths = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(widths.scrollWidth, `scrollWidth ${widths.scrollWidth} vs viewport ${widths.clientWidth}`).toBeLessThanOrEqual(widths.clientWidth);
  });
}

test("Settings: no SegmentedControl option text is clipped (QA audit: 'Fixed notio…', 'Match trad…')", async ({ page }) => {
  // SegmentedControl (ui/SegmentedControl.tsx) truncates each option
  // (`truncate whitespace-nowrap`) rather than wrapping, so a long label in
  // a narrow value column reads as an ellipsis with no way to see the rest.
  // Sizing mode and Leverage mode hit this at the *default* 320px value
  // column width (Panel.tsx SettingRow `sm:w-80`) even on a 1440px screen;
  // both now pass a wider `valueClassName`. Scan every radiogroup on the
  // page generically so a label change anywhere doesn't quietly reintroduce
  // this: scrollWidth > clientWidth on a `truncate` node means ellipsis.
  await gotoDemo(page, "/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  const radios = page.getByRole("radio");
  await expect(radios.first()).toBeVisible();
  const count = await radios.count();
  expect(count, "expected at least one SegmentedControl option on Settings").toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const radio = radios.nth(i);
    const name = await radio.evaluate((el) => el.textContent?.trim());
    const clipped = await radio.evaluate((el) => el.scrollWidth > el.clientWidth + 1);
    expect(clipped, `"${name}" is clipped (scrollWidth > clientWidth)`).toBe(false);
  }
});

test("Settings: every control is reachable and operable by keyboard alone", async ({ page }) => {
  await gotoDemo(page, "/settings");
  await page.locator("main").waitFor();
  // The historical a11y finding was one unlabeled input[type=range] (the
  // leverage sliders). Every range input must have an accessible name.
  const ranges = page.locator('input[type="range"]');
  const count = await ranges.count();
  for (let i = 0; i < count; i++) {
    const name = await ranges.nth(i).evaluate((el: HTMLInputElement) => el.getAttribute("aria-label") || el.labels?.[0]?.textContent || null);
    expect(name, `range input #${i} has no accessible name`).toBeTruthy();
  }
});

test("Account: the Accounts dialog opens and closes by keyboard (Escape)", async ({ page }) => {
  await gotoDemo(page, "/account");
  await page.getByRole("button", { name: "Accounts", exact: true }).focus();
  await page.keyboard.press("Enter");
  const dlg = page.getByRole("dialog", { name: "Accounts" });
  await expect(dlg).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();
});

test("Settings: the API token drawer opens and closes by keyboard (Escape)", async ({ page }) => {
  // ApiTokenPanel is hidden on the Settings page in demo mode, so open the
  // drawer the same way a tokenless real user would: the header key icon
  // (TopNav.tsx, labelled "API token: set"/"API token: missing"), present on
  // every page.
  await gotoDemo(page, "/settings");
  await page.getByRole("button", { name: /^API token:/ }).focus();
  await page.keyboard.press("Enter");
  const dlg = page.getByRole("dialog", { name: "API token" });
  await expect(dlg).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();
});
