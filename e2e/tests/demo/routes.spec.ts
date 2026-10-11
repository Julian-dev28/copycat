import { test, expect, ROUTES, gotoDemo, trackErrors } from "../../fixtures";

for (const route of ROUTES) {
  test(`demo ${route} renders with no page errors and no writes`, async ({ page, writes }) => {
    const errors = trackErrors(page);
    await gotoDemo(page, route);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("navigation").first()).toBeVisible();
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
