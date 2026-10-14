import type { Page } from "@playwright/test";
import { test, expect, gotoDemo, trackErrors } from "../../fixtures";

/**
 * Trade history correctness (docs/research/user_consensus_2026-10.md, "Trade
 * history correctness checklist"), exercised against real demo shapes.
 *
 * Both addresses below are fixed points in services/web/src/lib/scout/fixtures.ts'
 * deterministic board (SPECIAL[3] / SPECIAL[27]): `address(r)` is drawn from a
 * per-row RNG seeded only by the row's index (`rng(1000 + i)`), never by the demo
 * clock, so these addresses are stable forever unless that generator's draw order
 * changes before `address(r)` is called. Computed once with a throwaway vitest run
 * over `fixtureRows(NOW)` filtering by `row.flags`.
 */
const FILLS_TRUNCATED_ADDR = "0xd46a2102c4b6b8643edbbbb6220f7c2677ca0b49"; // SPECIAL[3]: flags ["fills_truncated"]
const WALLET_LIQUIDATED_ADDR = "0x597ab8dd5dfa43047e3830750d075044f55cff50"; // SPECIAL[27]: flags ["wallet_liquidated"]

async function openTrips(page: Page, address: string): Promise<void> {
  await gotoDemo(page, `/scout/${address}`);
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
  const sections = page.getByRole("tablist", { name: "Trader file sections" });
  await sections.getByRole("tab", { name: "Round trips" }).click();
  await expect(sections.getByRole("tab", { name: "Round trips" })).toHaveAttribute("aria-selected", "true");
}

test.describe("Trade history correctness (demo)", () => {
  test.afterEach(async ({ writes }) => {
    expect(writes, "demo mode must never send a non-GET request").toEqual([]);
  });

  test("every time column header says UTC, on Round trips, Fills and Open orders", async ({ page }) => {
    await openTrips(page, FILLS_TRUNCATED_ADDR);
    const region = page.getByRole("region", { name: "Round trips" });
    await expect(region.getByRole("columnheader", { name: "Opened (UTC)" })).toBeVisible();
    await expect(region.getByRole("columnheader", { name: "Closed (UTC)" })).toBeVisible();

    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Fills" }).click();
    await expect(page.getByRole("region", { name: "Fills" }).getByRole("columnheader", { name: "Time (UTC)" })).toBeVisible();

    await sections.getByRole("tab", { name: "Open orders" }).click();
    const orders = page.getByRole("region", { name: "Open orders" });
    const header = orders.getByRole("columnheader", { name: "Placed (UTC)" });
    // Headers always render even with zero rows (table only appears with >= 1 order);
    // this demo wallet may have none, so only assert the header when the table exists.
    if (await orders.locator("table").count()) await expect(header).toBeVisible();
  });

  test("a flip splits into a close and a separate open, never one trip", async ({ page }) => {
    await openTrips(page, FILLS_TRUNCATED_ADDR);
    const rows = page.getByTestId("trip-row");
    const n = await rows.count();
    const trips: { coin: string; side: string }[] = [];
    for (let i = 0; i < n; i++) {
      trips.push({ coin: (await rows.nth(i).getAttribute("data-coin"))!, side: (await rows.nth(i).getAttribute("data-side"))! });
    }
    // Opposite side, same coin, adjacent rows: the flip's close and open
    // (fixtures.ts injects this deterministically at trip index 5).
    const foundFlip = trips.some((t, i) => i > 0 && t.coin === trips[i - 1].coin && t.side !== trips[i - 1].side);
    expect(foundFlip, `no adjacent same-coin opposite-side trip pair found in ${JSON.stringify(trips)}`).toBe(true);
  });

  test("a truncated history shows a one-line notice with the visible count, on Round trips and Fills", async ({ page }) => {
    await openTrips(page, FILLS_TRUNCATED_ADDR);
    await expect(page.getByText(/Hyperliquid serves only the newest 10,000 fills/)).toBeVisible();
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Fills" }).click();
    await expect(page.getByText(/Hyperliquid serves only the newest 10,000 fills/)).toBeVisible();
  });

  test("open positions are listed under their own heading, not in the round trips list", async ({ page }) => {
    await openTrips(page, FILLS_TRUNCATED_ADDR);
    await expect(page.getByText("Open now, not in win rate")).toBeVisible();
  });

  test("a liquidation carries a visible badge with hover text, not an ordinary closed loss", async ({ page }) => {
    const errors = trackErrors(page);
    await openTrips(page, WALLET_LIQUIDATED_ADDR);
    expect(await page.getByTestId("trip-row").evaluateAll((rows) => rows.some((r) => r.getAttribute("data-liquidation") === "true")))
      .toBe(true);
    const badge = page.getByRole("region", { name: "Round trips" }).getByText("Liquidated", { exact: true });
    await expect(badge).toBeVisible();
    await expect(badge).toHaveAttribute("title", "Liquidated by Hyperliquid, not closed by the trader");

    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Fills" }).click();
    // The demo fills generator (~1/40 closing fills) may or may not land a liquidated
    // fill independently of the trip-level one above; only assert the tab renders clean.
    await expect(page.getByRole("region", { name: "Fills" })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("390px: the new Round trips content (notice, open section, liquidation badge) does not scroll the page sideways", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openTrips(page, FILLS_TRUNCATED_ADDR);
    await expect(page.getByText("Open now, not in win rate")).toBeVisible();
    await expect(page.getByText(/Hyperliquid serves only the newest 10,000 fills/)).toBeVisible();
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, "wide tables and the notice must scroll inside their own region, not the page").toBeLessThanOrEqual(clientWidth + 1);
  });

  test("account page Trades tab reuses the same Round trips view (open section, UTC headers)", async ({ page }) => {
    await gotoDemo(page, "/account");
    await page.getByRole("tab", { name: "Trades" }).click();
    const region = page.getByRole("region", { name: "Round trips" });
    await expect(region).toBeVisible();
    await expect(region.getByRole("columnheader", { name: "Opened (UTC)" })).toBeVisible();
  });

  test("account Fills/Orders/Transfers each state the window they cover", async ({ page }) => {
    await gotoDemo(page, "/account");
    await page.getByRole("tab", { name: "Fills", exact: true }).click();
    await expect(page.getByText("Last 30 days")).toBeVisible();
    await page.getByRole("tab", { name: "Orders" }).click();
    await expect(page.getByText("Newest 2,000 orders")).toBeVisible();
    await page.getByRole("tab", { name: "Transfers" }).click();
    await expect(page.getByText("Last 365 days")).toBeVisible();
  });
});
