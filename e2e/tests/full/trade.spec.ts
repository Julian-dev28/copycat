import { test, expect } from "../../fixtures";
import { ALPHA, api, mock, ordersFor, signIn } from "./_stack";

/**
 * The whole product end to end on the mock Hyperliquid: connect an API wallet through the
 * UI, make it active (the engine picks it up), go live in Settings (the real-money
 * confirmation), invest $100 in a leader from the Trade page; then the leader trades on
 * the mock and the engine mirrors the open and the close with orders signed by our agent
 * key, which the mock verifies like HL does. One story, one stack.
 */
test.describe.serial("full stack: connect, go live, copy; the engine mirrors the leader", () => {
  test.afterEach(async ({ errors }) => {
    expect(errors, "no uncaught page error").toEqual([]);
  });

  test("API wallet in, go live, copy mock-alpha; the engine mirrors its open and its close", async ({ page, request, stack }) => {
    test.setTimeout(240_000);
    const main = await mock(request, stack, "/__mock/keypair", {});
    const agent = await mock(request, stack, "/__mock/keypair", {});
    await mock(request, stack, "/__mock/user", { address: main.address, cash: 1000, agents: [{ address: agent.address }] });
    await signIn(page, stack);

    // 1. connect: paste the API wallet key (it lands in the stack's temp vault), make the account active
    await page.goto("/account");
    await page.getByRole("button", { name: "Connect an existing account" }).click();
    const dlg = page.getByRole("dialog", { name: "Connect an account" });
    await dlg.getByRole("radio", { name: "API key" }).click();
    await dlg.getByRole("textbox", { name: "Name" }).fill("e2e api wallet");
    await dlg.getByRole("textbox", { name: "Main account address" }).fill(main.address);
    await dlg.getByRole("textbox", { name: "API wallet private key" }).fill(agent.private_key);
    await dlg.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(dlg).toContainText("e2e api wallet is connected");
    await dlg.getByRole("button", { name: "Make active" }).click();
    await expect(page.getByRole("button", { name: /Active trading account e2e api wallet/ })).toBeVisible();
    // the engine (started by the harness once the vault existed) trades this account from its next cycle
    await expect.poll(async () => (await api(request, stack, "/api/status")).our_address, { timeout: 30_000 }).toBe(main.address);

    // 2. go live: trading on is one click; dry run off asks "Trade with real money?"
    await page.goto("/settings");
    const enabled = page.getByRole("switch", { name: "Trading enabled" });
    const dry = page.getByRole("switch", { name: "Dry run" });
    await expect(dry, "ships safe").toBeChecked();
    await enabled.click();
    await expect(enabled).toBeChecked();
    const confirm = page.getByRole("dialog", { name: "Trade with real money?" });
    await dry.click();
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(dry, "Cancel keeps dry run on").toBeChecked();
    await dry.click();
    await confirm.getByRole("button", { name: "Enable real trading" }).click();
    await expect(dry).not.toBeChecked();
    await expect.poll(async () => {
      const s = await api(request, stack, "/api/settings");
      return [s.enabled, s.dry_run];
    }).toEqual([true, false]);

    // 3. invest $100 in mock-alpha from the Trade page
    await page.goto("/");
    await page.getByRole("textbox", { name: "Search traders" }).fill(ALPHA);
    await page.getByRole("button", { name: /^mock-alpha/ }).click();
    const ticket = page.getByRole("region", { name: "Copy mock-alpha" });
    const copy = ticket.getByRole("button", { name: "Copy trader" });
    await expect(copy).toBeDisabled();
    await ticket.getByRole("textbox", { name: /^Invest/ }).fill("100");
    await expect(copy).toBeEnabled();
    await copy.click();
    const real = page.getByRole("dialog", { name: "Copy with real money?" });
    await expect(real, "a live copy asks first").toBeVisible();
    await real.getByRole("button", { name: "Copy for real" }).click();
    await expect(page.getByRole("tab", { name: /^Running 1/ })).toBeVisible();
    expect(await ordersFor(request, stack, main.address), "the leader is flat: nothing to mirror yet").toEqual([]);

    // 4. the leader opens 1 BTC on the mock; the engine mirrors it with an order signed by our agent
    await mock(request, stack, "/__mock/trade", { address: ALPHA, coin: "BTC", is_buy: true, sz: 1 });
    await expect.poll(() => ordersFor(request, stack, main.address), { message: "the engine's open", timeout: 60_000 })
      .toContainEqual(expect.objectContaining({ coin: "BTC", side: "buy", reduce_only: false }));
    const ours = (await mock(request, stack, "/__mock/state")).users[main.address].positions;
    expect(ours.BTC.szi).toBeGreaterThan(0);
    await page.goto("/portfolio");
    await expect(page.getByRole("heading", { name: /^Positions \(1\)/ })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("main")).toContainText("BTC");

    // 5. the leader closes; so do we, reduce-only, and both books are flat again
    await mock(request, stack, "/__mock/trade", { address: ALPHA, coin: "BTC", is_buy: false, sz: 1, reduce_only: true });
    await expect.poll(() => ordersFor(request, stack, main.address), { message: "the engine's close", timeout: 60_000 })
      .toContainEqual(expect.objectContaining({ coin: "BTC", side: "sell", reduce_only: true }));
    await expect.poll(async () => (await mock(request, stack, "/__mock/state")).users[main.address].positions,
      { timeout: 30_000 }).toEqual({});
    await expect(page.getByRole("heading", { name: /^Positions \(0\)/ })).toBeVisible({ timeout: 30_000 });
  });
});
