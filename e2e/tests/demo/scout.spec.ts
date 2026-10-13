import { test, expect, gotoDemo, trackErrors } from "../../fixtures";

test.describe("demo Scout", () => {
  test.afterEach(async ({ writes }) => {
    expect(writes, "demo mode must never send a non-GET request").toEqual([]);
  });

  test("board → trader file → Strategy tab", async ({ page }) => {
    const errors = trackErrors(page);
    await gotoDemo(page, "/scout");
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
    const cards = page.locator("main article");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(3);

    // a sort changes the order; a window change keeps the board populated
    const firstBefore = await cards.first().innerText();
    await page.getByRole("combobox", { name: "Sort" }).selectOption({ label: "Largest account" });
    await expect.poll(() => cards.first().innerText()).not.toEqual(firstBefore);
    await page.getByRole("radiogroup", { name: "PnL window" }).getByRole("radio", { name: "7d" }).click();
    await expect(cards.first()).toBeVisible();

    // open the 2nd card's file (not the already-copied first one): TraderCard's link
    // text is "Open trader" (bits.tsx/TraderCard.tsx), not "trader file"
    const card = cards.nth(1);
    const fileLink = card.getByRole("link", { name: /open trader/i });
    const href = await fileLink.getAttribute("href");
    expect(href).toMatch(/^\/scout\/0x[0-9a-f]{40}\?demo=1$/);
    await fileLink.click();
    await expect(page).toHaveURL(/\/scout\/0x[0-9a-f]{40}\?demo=1/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    for (const name of ["Round trips", "Fills", "Open orders"]) {
      await sections.getByRole("tab", { name }).click();
      await expect(sections.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
    }
    await sections.getByRole("tab", { name: "Strategy" }).click();
    const strategy = page.getByRole("tabpanel", { name: "Strategy" });
    await expect(strategy.getByRole("term").filter({ hasText: "Trips analyzed" })).toBeVisible();
    await expect(strategy).toContainText(/no AI/);
    expect(errors).toEqual([]);
  });

  test("Add to copies from the board marks the card as copying", async ({ page }) => {
    await gotoDemo(page, "/scout");
    const card = page.locator("main article").filter({ has: page.getByRole("button", { name: "Add to copies" }) }).first();
    const name = (await card.innerText()).split("\n").slice(0, 2).join(" ");
    await card.getByRole("button", { name: "Add to copies" }).click();
    const same = page.locator("main article").filter({ hasText: name.split(" ").slice(1, 2).join(" ") }).first();
    await expect(same.getByRole("button", { name: /Already copying|Copying/ })).toBeVisible();
  });

  test("Discover runs a canned scan with the inputs given", async ({ page }) => {
    const errors = trackErrors(page);
    await gotoDemo(page, "/discover");
    await expect(page.getByRole("heading", { level: 1, name: "Discover" })).toBeVisible();
    // 1010, not the default 1000: see the KNOWN BUG test below
    await page.getByRole("spinbutton", { name: /Simulated equity/ }).fill("1010");
    await page.getByRole("spinbutton", { name: /Wallets to scan/ }).fill("10");
    await page.getByRole("button", { name: "Start discovery run" }).click();
    await expect(page.getByRole("heading", { name: /Results \(10\)/ })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Sort by Max DD" }).click();
    expect(errors).toEqual([]);
  });

  test("the default Discover form is valid and submits", async ({ page }) => {
    // Regression: DiscoveryForm once had min={10} step={100}, which made the default 1000
    // invalid (valid: 910, 1010), so Start silently did nothing.
    await gotoDemo(page, "/discover");
    const eq = page.getByRole("spinbutton", { name: /Simulated equity/ });
    expect(await eq.evaluate((el: HTMLInputElement) => el.validity.valid)).toBe(true);
    await page.getByRole("button", { name: "Start discovery run" }).click();
    await expect(page.getByRole("heading", { name: /Results \(/ })).toBeVisible({ timeout: 20_000 });
  });
});
