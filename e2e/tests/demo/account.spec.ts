import type { Page } from "@playwright/test";
import { test, expect, gotoDemo, trackErrors } from "../../fixtures";

const PASS = "correct horse battery staple";

async function openAccounts(page: Page) {
  await gotoDemo(page, "/account");
  await page.getByRole("button", { name: "Accounts", exact: true }).click();
  return page.getByRole("dialog", { name: "Accounts" });
}

const accountItems = (page: Page) =>
  page.getByRole("list", { name: "Your trading accounts" }).getByRole("listitem");

test.describe("demo Account", () => {
  test.afterEach(async ({ writes }) => {
    expect(writes, "demo mode must never send a non-GET request").toEqual([]);
  });

  test("loading shows visible text, not three bare pulsing boxes (QA audit)", async ({ page }) => {
    // app/account/page.tsx wraps the (client) page in <Suspense fallback={<PageSkeleton
    // label="Loading account" />}>: real-world, this shows for however long the route's
    // JS takes to arrive, which on a slow connection or a loaded dev server can run
    // past 2s. Slow every script response so that window is wide enough to assert on,
    // same as a user on a bad connection would actually see.
    await page.route("**/*", async (route) => {
      if (route.request().resourceType() === "script") await new Promise((r) => setTimeout(r, 400));
      await route.continue();
    });
    const loaded = page.goto("/account?demo=1");
    // PageSkeleton used to say "Loading account" only to a screen reader (sr-only);
    // a sighted user saw nothing but empty pulsing boxes for the whole wait.
    await expect(page.getByText("Loading account…")).toBeVisible();
    await loaded;
    await page.unroute("**/*");
    await expect(page.getByRole("button", { name: "Accounts", exact: true })).toBeVisible({ timeout: 15_000 });
  });

  test("create: passphrase, key shown once, 'I saved my key' gate", async ({ page }) => {
    const errors = trackErrors(page);
    await openAccounts(page);
    const before = await accountItems(page).count();
    await page.getByRole("button", { name: /^Create a new account/ }).click();
    const dlg = page.getByRole("dialog").last();
    await dlg.getByRole("textbox", { name: "Name" }).fill("e2e created");
    await dlg.getByRole("textbox", { name: "Passphrase", exact: true }).fill(PASS);
    await dlg.getByRole("textbox", { name: "Passphrase again" }).fill(PASS);
    await dlg.getByRole("button", { name: "Create wallet" }).click();
    // the key is revealed once and the flow cannot finish until the user confirms the backup
    const saved = page.getByRole("checkbox", { name: /I saved my key/i });
    await expect(saved).toBeVisible();
    const done = page.getByRole("dialog").last().getByRole("button", { name: /^(Done|Continue|Finish)/ });
    await expect(done).toBeDisabled();
    await saved.check();
    await expect(done).toBeEnabled();
    await done.click();
    // "Continue to funding" moves the SAME dialog to its fund step (by design:
    // one continuous session from create through funding); it never closes on
    // its own, so close it here before reopening Accounts to check the list.
    await page.getByRole("heading", { name: "Fund your wallet" }).waitFor();
    await page.getByRole("dialog").last().getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "Accounts", exact: true }).click();
    await expect(accountItems(page)).toHaveCount(before + 1);
    await expect(accountItems(page).filter({ hasText: "e2e created" })).toHaveCount(1);
    expect(errors).toEqual([]);
  });

  test("connect by signing with the fake wallet", async ({ page }) => {
    await openAccounts(page);
    await page.getByRole("button", { name: /^Connect an existing account/ }).click();
    const dlg = page.getByRole("dialog").last();
    await dlg.getByRole("textbox", { name: "Name" }).fill("e2e signed");
    await expect(dlg.getByRole("combobox", { name: "Demo wallet" })).toHaveValue(/approve/i);
    await dlg.getByRole("button", { name: "Connect wallet" }).click();
    await expect(dlg.getByText("e2e signed is connected")).toBeVisible({ timeout: 15_000 });
    await dlg.getByRole("button", { name: "Done" }).click();
    await page.getByRole("button", { name: "Accounts", exact: true }).click();
    await expect(accountItems(page).filter({ hasText: "e2e signed" })).toHaveCount(1);
  });

  test("connect: a rejected signature is reported, nothing is added", async ({ page }) => {
    await openAccounts(page);
    const before = await accountItems(page).count();
    await page.getByRole("button", { name: /^Connect an existing account/ }).click();
    const dlg = page.getByRole("dialog").last();
    // Required before the form will submit at all (SignWithWallet.tsx checkLabel):
    // without it, "Connect wallet" just shows "Give it a name." and the demo
    // wallet mode below is never exercised.
    await dlg.getByRole("textbox", { name: "Name" }).fill("e2e rejected");
    await dlg.getByRole("combobox", { name: "Demo wallet" }).selectOption({ label: "Rejects signature" });
    await dlg.getByRole("button", { name: "Connect wallet" }).click();
    // Not a text search: the dialog's own <select> has an option literally
    // named "Rejects signature", which a loose /reject/i text match finds
    // first (hidden, since the select is closed) and never looks past. The
    // "Try again" button is the real, semantic signal that the flow erred
    // (SignWithWallet.tsx: state.step === "error" renders it in place of
    // "Connect wallet").
    await expect(dlg.getByRole("button", { name: "Try again" })).toBeVisible({ timeout: 15_000 });
    await dlg.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "Accounts", exact: true }).click();
    await expect(accountItems(page)).toHaveCount(before);
  });

  test("connect by API key: the form validates before it submits", async ({ page }) => {
    await openAccounts(page);
    await page.getByRole("button", { name: /^Connect an existing account/ }).click();
    const dlg = page.getByRole("dialog").last();
    await dlg.getByRole("radio", { name: "API key" }).click();
    const submit = dlg.getByRole("button", { name: "Connect", exact: true });
    const before = await page.getByRole("list", { name: "Your trading accounts" }).count();
    await submit.click();
    await expect(dlg.getByRole("textbox", { name: /address/i })).toBeVisible();
    expect(await page.getByRole("list", { name: "Your trading accounts" }).count()).toBe(before);
    await dlg.getByRole("textbox", { name: /address/i }).fill("0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc");
    // a throwaway test key (well-known hardhat #1). Never a real key.
    await dlg.getByRole("textbox", { name: /key/i }).fill("0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d");
    await submit.click();
    await expect(dlg.getByText(/connected|added|approved|not an approved|agent/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("funding: move, send, withdraw run in memory; deposit shows the bridge facts", async ({ page }) => {
    await gotoDemo(page, "/account");
    const funding = page.getByRole("group", { name: "Funding" });

    await funding.getByRole("button", { name: "Deposit" }).click();
    const dep = page.getByRole("dialog", { name: /^Deposit to/ });
    await expect(dep.getByRole("radio", { name: "From Arbitrum" })).toBeChecked();
    await expect(dep).toContainText(/Minimum\s*5 USDC/);
    await dep.getByRole("button", { name: "Close" }).click();

    await funding.getByRole("button", { name: "Move" }).click();
    const move = page.getByRole("dialog", { name: /^Move USDC/ });
    await move.getByRole("textbox", { name: "Amount" }).fill("10");
    await move.getByRole("textbox", { name: "Passphrase" }).fill(PASS);
    // Not exact: once an amount is typed the submit button's accessible name
    // grows to "Move $10.00" (MoneyActionDialog.tsx: `${TITLE[kind].split(" ")[0]}{amt ? ... }`).
    await move.getByRole("button", { name: /^Move/ }).click();
    await expect(page.getByText(/moved|done|sent|success/i).first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("Escape");

    await funding.getByRole("button", { name: "Withdraw" }).click();
    const wd = page.getByRole("dialog", { name: /^Withdraw/ });
    await wd.getByRole("textbox", { name: "Amount" }).fill("0.5");
    await wd.getByRole("textbox", { name: "Passphrase" }).fill(PASS);
    // below the $1 fee: must not be submittable
    await expect(wd.getByRole("button", { name: /^Withdraw/ })).toBeDisabled();
    await wd.getByRole("textbox", { name: "Amount" }).fill("20");
    await wd.getByRole("button", { name: /^Withdraw/ }).click();
    await expect(page.getByText(/withdraw.*(sent|submitted|requested|done)|on its way/i).first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("Escape");

    await funding.getByRole("button", { name: "Send" }).click();
    const send = page.getByRole("dialog", { name: /^Send USDC/ });
    await send.getByRole("radio", { name: /Ledger via Rabby/ }).click();
    await send.getByRole("textbox", { name: "Amount" }).fill("5");
    await send.getByRole("textbox", { name: "Passphrase" }).fill(PASS);
    await send.getByRole("button", { name: /^Send/ }).click();
    await expect(page.getByText(/sent|done|success/i).first()).toBeVisible({ timeout: 15_000 });
  });
});
