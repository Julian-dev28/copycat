import { test, expect, gotoDemo } from "../../fixtures";

/**
 * Portfolio-only regressions from the underwhelm sweep
 * (docs/qa/underwhelm_2026-10-14.md). Scout/Settings/Account/Trade have
 * their own files; this one is Portfolio's.
 */
test.describe("demo Portfolio", () => {
  test.afterEach(async ({ writes }) => {
    expect(writes, "demo mode must never send a non-GET request").toEqual([]);
  });

  test("empty Positions: 'Check your copies' jumps to Your copies on this page, not a dead /copy route", async ({ page }) => {
    await gotoDemo(page, "/portfolio");
    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
    const link = page.getByRole("link", { name: "Check your copies" });
    // Regression: this used to point at "/copy", a removed legacy route that
    // redirects to /settings (lib/trade/apiState.ts LEGACY_ROUTES) -- nothing
    // to do with "your copies", which sits in the panel right above.
    await expect(link).toHaveAttribute("href", "#your-copies");
    await link.click();
    await expect(page).toHaveURL(/\/portfolio\?demo=1#your-copies$/);
    await expect(page.getByRole("heading", { level: 2, name: "Your copies" })).toBeInViewport();
  });
});
