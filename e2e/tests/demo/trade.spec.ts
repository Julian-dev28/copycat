import { test, expect, gotoDemo, trackErrors } from "../../fixtures";

test.describe("demo Trade copy flow", () => {
  test("custom copy: amount, preview, copy, appears in Your copies", async ({ page, writes }) => {
    const errors = trackErrors(page);
    await gotoDemo(page, "/");
    const copyBtn = page.getByRole("button", { name: "Copy trader" });
    await expect(copyBtn).toBeDisabled();
    await page.getByRole("textbox", { name: /^Invest/ }).fill("100");
    await expect(copyBtn).toBeEnabled();
    await copyBtn.click();
    await expect(page.getByRole("tab", { name: /Running 1/ })).toBeVisible();
    await page.screenshot({ path: "artifacts/scratch-after-copy.png", fullPage: true });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
});
