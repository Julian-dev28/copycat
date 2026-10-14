import { test, expect } from "../../fixtures";
import { ALPHA, api, mock, refreshScout, signIn } from "./_stack";

/**
 * Scout on the real api + scout process against the mock Hyperliquid: the board builds
 * itself from the mock leaderboard, a leader's round trip reaches its file, and a change
 * of sim terms re-ranks from cache without a single candle read. Serial: the tests share
 * one stack and build on each other (the trade seeded in the second is the cache the
 * third re-sims from).
 */
test.describe.serial("full stack: Scout", () => {
  test.afterEach(async ({ errors }) => {
    expect(errors, "no uncaught page error").toEqual([]);
  });

  test("no token: the page asks for it and sends nothing; saving the stack token opens Scout", async ({ page, stack, writes }) => {
    await page.goto("/scout");
    await expect(page.getByRole("heading", { name: "Enter your API token" })).toBeVisible();
    expect(writes, "nothing is written before a token exists").toEqual([]);
    // the API token drawer opens on its own when no token is stored ("Open settings" reopens it)
    const dlg = page.getByRole("dialog", { name: "API token" });
    await expect(dlg).toBeVisible();
    await dlg.getByRole("textbox", { name: "Bearer token" }).fill(stack.token!);
    await dlg.getByRole("button", { name: "Save token" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
  });

  test("the board ranks the mock leaderboard; a leader's round trip reaches its file with UTC times", async ({ page, request, stack }) => {
    // mock-alpha opens 1 BTC at $100K and closes at $101K: one long round trip, +$1,000 before fees
    const t0 = Date.now();
    await mock(request, stack, "/__mock/trade", { address: ALPHA, coin: "BTC", is_buy: true, sz: 1, time: t0 });
    await mock(request, stack, "/__mock/mids", { BTC: 101_000 });
    await mock(request, stack, "/__mock/trade", { address: ALPHA, coin: "BTC", is_buy: false, sz: 1, reduce_only: true, time: t0 + 1 });
    await refreshScout(request, stack);

    await signIn(page, stack);
    await page.goto("/scout");
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
    const cards = page.locator("main article");
    await expect(cards).toHaveCount(3);
    await expect(page.getByRole("status").filter({ hasText: /ranked/ })).toContainText("3 ranked");
    for (const name of ["mock-alpha", "mock-beta", "mock-gamma"]) await expect(page.getByRole("main")).toContainText(name);
    const alpha = cards.filter({ hasText: "mock-alpha" });
    await expect(alpha).toHaveCount(1);
    await expect(alpha).not.toContainText("no trades in 30d");
    // the mock quotes HYPE/USDC, so the extras read (spot + staked) succeeds like it does on HL
    await expect(alpha).not.toContainText("extras unavailable");

    await alpha.getByRole("link", { name: "Open trader" }).click();
    await expect(page).toHaveURL(new RegExp(`/scout/${ALPHA}$`));
    await expect(page.getByRole("heading", { level: 1, name: "mock-alpha" })).toBeVisible();
    const sections = page.getByRole("tablist", { name: "Trader file sections" });
    await sections.getByRole("tab", { name: "Round trips" }).click();
    const trips = page.getByTestId("trip-row");
    await expect(trips).toHaveCount(1);
    await expect(trips.first()).toHaveAttribute("data-coin", "BTC");
    await expect(trips.first()).toHaveAttribute("data-side", /long/i);
    await expect(trips.first()).toContainText(/\+\$/); // a winner
    await expect(page.getByRole("region", { name: "Round trips" }).getByRole("columnheader", { name: "Opened (UTC)" })).toBeVisible();

    await sections.getByRole("tab", { name: "Fills" }).click();
    const fills = page.getByRole("region", { name: "Fills" });
    await expect(fills.getByRole("columnheader", { name: "Time (UTC)" })).toBeVisible();
    await expect(fills.getByRole("row")).toHaveCount(1 + 2); // header, open, close
  });

  test("Sim terms: new terms re-rank the board from cache, without a candle read", async ({ page, request, stack }) => {
    const before = (await mock(request, stack, "/__mock/state")).info_counts;
    await signIn(page, stack);
    await page.goto("/scout");
    await expect(page.getByText(/with \$100 at 3x leverage/)).toBeVisible();
    await page.getByRole("button", { name: "Sim terms" }).click();
    const dlg = page.getByRole("dialog", { name: "Sim terms" });
    await dlg.getByRole("textbox", { name: "Per wallet $" }).fill("200");
    await dlg.getByRole("textbox", { name: "Leverage x" }).fill("5");
    await dlg.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText(/with \$200 at 5x leverage/)).toBeVisible({ timeout: 30_000 });
    expect(await api(request, stack, "/api/scout/sim-terms")).toMatchObject({ allocation_usd: 200, leverage: 5, leverage_mode: "fixed" });
    await expect.poll(async () => (await api(request, stack, "/api/scout/traders?limit=1")).stale_settings,
      { message: "the board republished at the new terms", timeout: 60_000 }).toBe(false);
    await expect(page.locator("main article")).toHaveCount(3);
    const after = (await mock(request, stack, "/__mock/state")).info_counts;
    expect(after.candleSnapshot ?? 0, "a terms change re-sims from the candle cache").toBe(before.candleSnapshot ?? 0);
  });
});
