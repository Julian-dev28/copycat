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

  test("Copyable preset: the chip carries a count and keeps only wallets the sim could follow", async ({ page }) => {
    await gotoDemo(page, "/scout");
    const all = await page.locator("main article").count();
    const chip = page.getByRole("group", { name: "Presets" }).getByRole("button", { name: /^Copyable/ });
    await expect(chip).toBeVisible();
    const count = Number((await chip.innerText()).replace(/\D/g, ""));
    expect(count).toBeGreaterThan(0);
    await chip.click();
    await expect(page).toHaveURL(/preset=copyable/);
    await expect(page.locator("main article")).toHaveCount(Math.min(count, all));
  });

  test("add a custom wallet from the board: file opens, Custom preset shows it, remove takes it off", async ({ page }) => {
    const errors = trackErrors(page);
    const addr = "0x" + "5a".repeat(20);     // not on the demo board
    await gotoDemo(page, "/scout");
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
    // no custom wallets yet: no Custom chip
    await expect(page.getByRole("group", { name: "Presets" }).getByRole("button", { name: /^Custom/ })).toHaveCount(0);

    const box = page.getByRole("textbox", { name: "Add a wallet to Scout" });
    // garbage is refused inline, no navigation
    await box.fill("vitalik.eth");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /not a wallet address/ })).toBeVisible();
    await expect(page).toHaveURL(/\/scout\?demo=1$/);

    await box.fill(`https://app.hyperliquid.xyz/explorer/address/${addr}`);
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/scout/${addr}\\?demo=1`));
    await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
    await expect(page.getByText("Custom", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Remove from Scout" })).toBeVisible();

    // back on the board, the Custom preset lists it with the badge
    await gotoDemo(page, "/scout", "&preset=custom");
    const chip = page.getByRole("group", { name: "Presets" }).getByRole("button", { name: /^Custom/ });
    await expect(chip).toHaveAttribute("aria-pressed", "true");
    const cards = page.locator("main article");
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText(addr.slice(0, 6));
    await expect(cards.first().getByText("Custom", { exact: true })).toBeVisible();

    // remove it: the card goes and so does the chip
    await cards.first().getByRole("button", { name: /Remove .* from Scout/ }).click();
    await expect(page.getByText("Removed from Scout")).toBeVisible();
    await expect(page.locator("main article")).toHaveCount(0);
    await gotoDemo(page, "/scout");
    await expect(page.getByRole("group", { name: "Presets" }).getByRole("button", { name: /^Custom/ })).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("Sim terms control updates the page note and re-ranks the board", async ({ page }) => {
    const errors = trackErrors(page);
    await gotoDemo(page, "/scout");
    await expect(page.getByRole("heading", { level: 1, name: "Scout" })).toBeVisible();
    // the default reference terms (contracts/models.py ScoutSimTerms() field defaults:
    // measured on a real-HL throwaway stack, see scout/README.md "Sim terms")
    // Chromium's Intl.NumberFormat compact currency drops the decimal for round sub-1000/K
    // values ("$100", "$1K"); Node's (vitest/jsdom, lib/scout/simTerms.test.ts) does not
    // ("$100.0", "$1.0K"). Same formatUsd call, two ICU implementations: assert what each
    // runtime actually renders rather than fight it.
    await expect(page.getByText(/Ranked by what copying each wallet with \$100 at 3x leverage/)).toBeVisible();

    const cards = page.locator("main article");
    await expect(cards.first()).toBeVisible();
    const firstBefore = await cards.first().innerText();

    await page.getByRole("button", { name: "Sim terms" }).click();
    const drawer = page.getByRole("dialog", { name: "Sim terms" });
    await expect(drawer).toBeVisible();
    // the default is already "Fixed" leverage (3x); just change the numbers
    await expect(drawer.getByRole("radiogroup", { name: "Leverage mode" }).getByRole("radio", { name: "Fixed" }))
      .toHaveAttribute("aria-checked", "true");
    await drawer.getByLabel("Account equity").fill("5000");
    await drawer.getByLabel("Per wallet").fill("500");
    // The NumberField's accessible name picks up its trailing unit span ("x") too, and
    // "Leverage" alone also substring-matches the "Leverage mode" radiogroup above, so
    // target the input by id rather than guess the exact computed name.
    await drawer.locator("#st-lev").fill("25");
    await drawer.getByRole("button", { name: "Apply" }).click();
    await expect(drawer).toBeHidden();

    // the note reflects the NEW terms, not the old ones: $500 allocation, fixed 25x, $5K account
    await expect(page.getByText(/Ranked by what copying each wallet with \$500 at 25x leverage would have earned a \$5K account/)).toBeVisible();
    // and the board actually re-ranked (deterministic demo re-sim, lib/scout/fixtures.ts::applySimTerms)
    await expect.poll(() => cards.first().innerText()).not.toEqual(firstBefore);
    expect(errors).toEqual([]);
  });

  test("Sim terms: 'Their leverage' choice shows the capped-leverage wording", async ({ page }) => {
    await gotoDemo(page, "/scout");
    await page.getByRole("button", { name: "Sim terms" }).click();
    const drawer = page.getByRole("dialog", { name: "Sim terms" });
    await drawer.getByRole("radiogroup", { name: "Leverage mode" }).getByRole("radio", { name: "Their leverage" }).click();
    await drawer.locator("#st-lev").fill("8");
    await drawer.getByRole("button", { name: "Apply" }).click();
    await expect(drawer).toBeHidden();
    await expect(page.getByText(/Ranked by what copying each wallet with \$100 at their leverage \(8x cap\)/)).toBeVisible();
  });

  test("Sim terms: switching to live settings changes the note to the settings-based wording", async ({ page }) => {
    await gotoDemo(page, "/scout");
    await page.getByRole("button", { name: "Sim terms" }).click();
    const drawer = page.getByRole("dialog", { name: "Sim terms" });
    await drawer.getByRole("switch", { name: "Use my live trading settings" }).click();
    await drawer.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText("Ranked by what copying each wallet at your own trading settings would have earned you over the last 30 days.")).toBeVisible();
  });
});
