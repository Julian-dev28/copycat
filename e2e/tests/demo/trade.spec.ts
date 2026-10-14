import type { Locator, Page } from "@playwright/test";
import { test, expect, gotoDemo } from "../../fixtures";

const invest = (page: Page) => page.getByRole("textbox", { name: /^Invest/ });
const backtest = (page: Page) => page.getByRole("region", { name: /backtest/i });
const copiesTab = (page: Page, name: "Running" | "Stopped" | "Archived") =>
  page.getByRole("tab", { name: new RegExp(`^${name} \\d+`) });
const firstCopyRow = (page: Page) =>
  page.getByRole("table").filter({ has: page.getByRole("columnheader", { name: "Invested" }) })
    .getByRole("row").nth(1);
const btn = (scope: Locator, name: string) => scope.getByRole("button", { name, exact: true });

async function backtestText(page: Page): Promise<string> {
  const r = backtest(page);
  await expect(r).toContainText(/Return/);
  await page.waitForTimeout(300); // the sim re-renders after a debounce
  return (await r.innerText()).replace(/\s+/g, " ");
}

/** Wait until the backtest differs from `prev` (it recomputes after a debounce) and return it. */
async function changedFrom(page: Page, prev: string, why: string): Promise<string> {
  await expect.poll(() => backtestText(page), { message: why, timeout: 8000 }).not.toEqual(prev);
  return backtestText(page);
}

async function setLeverage(page: Page, key: "Home" | "End") {
  await page.getByRole("radio", { name: "Set leverage" }).click();
  const slider = page.getByRole("slider", { name: /leverage/i });
  await slider.focus();
  await slider.press(key);
  return slider;
}

test.describe("demo Trade", () => {
  test.afterEach(async ({ writes, errors }) => {
    expect(writes, "demo mode must never send a non-GET request").toEqual([]);
    // Every Trade flow goes through this: a hydration crash or a native call
    // with the wrong receiver (e.g. the toastStore "Illegal invocation" bug,
    // only reproducible in a real browser, not jsdom) must fail every test
    // in this file, not just the one that happened to assert on it by hand.
    expect(errors, "no uncaught page error").toEqual([]);
  });

  test("custom copy lands in Running with the invested amount", async ({ page }) => {
    await gotoDemo(page, "/");
    const copy = page.getByRole("button", { name: "Copy trader" });
    await expect(copy).toBeDisabled();
    await invest(page).fill("100");
    await expect(copy).toBeEnabled();
    await copy.click();
    // Two separate confirmations: the ticket's own inline line, and the toast
    // (toastStore regression: a real browser threw "Illegal invocation" on
    // every toast before it reached its first subscriber notification, so
    // the toast queue was silently empty and <Toaster> never rendered one).
    await expect(page.getByTestId("ticket-action-bar").getByRole("status")).toContainText("$100.00");
    await expect(page.getByLabel("Notifications").getByRole("status")).toContainText("$100.00");
    await expect(copiesTab(page, "Running")).toHaveAccessibleName(/Running 1/);
    const row = firstCopyRow(page);
    await expect(row).toContainText("$100.00");
    await expect(row).toContainText(/Custom/);
  });

  test("global copy uses Settings terms", async ({ page }) => {
    await gotoDemo(page, "/");
    await page.getByRole("radio", { name: "Use global" }).click();
    await expect(page.getByRole("link", { name: "Edit in Settings" })).toBeVisible();
    await page.getByRole("button", { name: /Copy with global settings/ }).click();
    await expect(copiesTab(page, "Running")).toHaveAccessibleName(/Running 1/);
    await expect(firstCopyRow(page)).not.toContainText(/Custom/);
  });

  test("counter inverts the backtest and the button", async ({ page }) => {
    await gotoDemo(page, "/");
    await invest(page).fill("100");
    const copied = await backtestText(page);
    await page.getByRole("radio", { name: "Counter" }).click();
    await expect(page.getByRole("button", { name: "Counter trader" })).toBeVisible();
    await expect(backtest(page)).toContainText(/countered/);
    await changedFrom(page, copied, "counter must change the backtest");
    await page.getByRole("button", { name: "Counter trader" }).click();
    await expect(copiesTab(page, "Running")).toHaveAccessibleName(/Running 1/);
  });

  test("changing an input changes the backtest; a display-only input does not", async ({ page }) => {
    await gotoDemo(page, "/");
    await invest(page).fill("100");
    const at100 = await backtestText(page);
    await invest(page).fill("300");
    await expect(backtest(page)).toContainText("$300.00");
    const follow = await changedFrom(page, at100, "amount must change the backtest");
    const slider = await setLeverage(page, "End");
    const max = await changedFrom(page, follow, "max leverage must change the backtest vs follow-his-leverage");
    await slider.press("Home");
    await expect(slider).toHaveValue("1");
    const one = await changedFrom(page, max, "1x must change the backtest vs max leverage");
    expect(one, "1x cannot liquidate").toMatch(/liquidations 0\b/i);
    // the chart window is display-only: it must not change the backtest
    await page.getByRole("radiogroup", { name: "Chart window" }).getByRole("radio", { name: "7d" }).click();
    expect(await backtestText(page)).toEqual(one);
  });

  test("leverage cap message offers a way to raise it, not just the bad news (QA audit)", async ({ page }) => {
    // Default demo settings: max_position_leverage 50 == MAX_LEVERAGE_CAP, so
    // the ticket's own max (50x, Home/End on the slider) never caps on its
    // own; lower the Settings cap first so sliding to End trips it for sure.
    await gotoDemo(page, "/settings");
    const maxLev = page.getByRole("slider", { name: "Maximum position leverage" });
    await maxLev.focus();
    await maxLev.press("Home"); // 1x
    await page.waitForTimeout(600); // the patch is debounced 350ms and cancelled on unmount
    await page.getByRole("link", { name: "Trade" }).click();
    await page.locator("main").waitFor();
    await invest(page).fill("250");
    const slider = await setLeverage(page, "End");
    await expect(slider).toHaveValue("50");
    const capped = page.getByTestId("ticket-leverage-capped");
    await expect(capped).toBeVisible();
    // Regression: this used to state the cap with no way out of it.
    const raise = capped.getByRole("link", { name: "Raise the cap" });
    await expect(raise).toHaveAttribute("href", /\/settings\?demo=1.*#max_position_leverage/);
    await raise.click();
    await expect(page).toHaveURL(/\/settings\?demo=1.*#max_position_leverage/);
    await expect(maxLev).toBeInViewport(); // the browser scrolls the #max_position_leverage target into view
  });

  test("coin filters are editable", async ({ page }) => {
    await gotoDemo(page, "/");
    const only = page.getByRole("combobox", { name: "Only these coins" });
    await only.click();
    await only.fill("ETH");
    await only.press("Enter");
    // Scoped to the chip itself: a bare `getByText(/ETH/)` also matches the
    // (closed) suggestion listbox option sharing the same "ETH" text node shape.
    await expect(page.getByRole("button", { name: "Remove ETH from Only these coins" })).toBeVisible();
  });

  test("pause, resume, log drawer, share card, stop and close, archive", async ({ page }) => {
    await gotoDemo(page, "/");
    await invest(page).fill("100");
    await page.getByRole("button", { name: "Copy trader" }).click();
    const row = firstCopyRow(page);
    await btn(row, "Pause").click();
    await expect(row).toContainText(/paused/);
    await btn(row, "Resume").click();
    await expect(row).toContainText(/running/);

    await btn(row, "Log").click();
    const log = page.getByRole("dialog", { name: /^Log for/ });
    await expect(log.getByRole("list", { name: "Wallet events" }).getByRole("listitem").first()).toBeVisible();
    await log.getByRole("radio", { name: "Skips" }).click();
    for (const item of await log.getByRole("listitem").all()) await expect(item).toContainText(/skip/i);
    await log.getByRole("button", { name: "Close the log" }).click();
    await expect(log).toBeHidden();

    await btn(row, "Share PnL").click();
    const share = page.getByRole("dialog", { name: "Share your PnL" });
    await expect(share.getByRole("button", { name: "Download" })).toBeVisible();
    await share.getByRole("button", { name: "Close" }).click();
    await expect(share).toBeHidden();

    await btn(row, "Stop").click();
    const stop = page.getByRole("dialog", { name: /^Stop copying/ });
    await expect(stop.getByRole("radio", { name: /Close positions now/ })).toBeChecked();
    await stop.getByRole("button", { name: "Stop and close" }).click();
    await expect(copiesTab(page, "Running")).toHaveAccessibleName(/Running 0/);
    await copiesTab(page, "Stopped").click();
    await expect(copiesTab(page, "Stopped")).toHaveAccessibleName(/Stopped 1/);
    await btn(firstCopyRow(page), "Archive").click();
    const confirm = page.getByRole("dialog", { name: /^Archive/ });
    const archiveBtn = confirm.getByRole("button", { name: "Archive", exact: true });
    await expect(archiveBtn).toBeDisabled();
    await confirm.getByRole("textbox").fill("archive");
    await archiveBtn.click();
    await expect(copiesTab(page, "Archived")).toHaveAccessibleName(/Archived 1/);
  });

  test("paste an address selects that wallet", async ({ page }) => {
    await gotoDemo(page, "/");
    await page.getByRole("textbox", { name: "Search traders" }).fill("0x2222222222222222222222222222222222222222");
    await page.getByRole("button", { name: /^0x22…2222/ }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("0x2222");
  });

  test("account size switch changes free margin", async ({ page }) => {
    await gotoDemo(page, "/", "&acct=small");
    await expect(invest(page)).toHaveAccessibleName(/\$20\.00/);
    await gotoDemo(page, "/", "&acct=large");
    await expect(invest(page)).toHaveAccessibleName(/\$1M/);
  });
});
