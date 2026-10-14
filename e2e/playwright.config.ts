import { defineConfig, devices } from "@playwright/test";

/**
 * copycat e2e lane (see README.md). `npm run demo` / `make e2e-demo`: demo + a11y + visual
 * (web only, no backend). `npm run full`: the full stack against the mock Hyperliquid (one
 * worker, serial); `make e2e` runs demo, then full.
 * baseURL comes from the stack global-setup starts (fixtures.ts reads e2e/.stack.json).
 */
export default defineConfig({
  testDir: "tests",
  outputDir: "artifacts/test-results",
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "artifacts/report", open: "never" }]],
  use: {
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "demo", testDir: "tests/demo" },
    { name: "a11y", testDir: "tests/a11y" },
    { name: "visual", testDir: "tests/visual" },
    { name: "full", testDir: "tests/full", fullyParallel: false, timeout: 120_000 },
  ],
});
