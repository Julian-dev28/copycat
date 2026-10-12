/** Debug helper: dump the ARIA tree of demo pages from a running stack (node harness/cli.ts up web first).
 *    node harness/aria-dump.ts "/?demo=1" "/scout?demo=1" ...   -> artifacts/aria/*.yml */
import { chromium } from "@playwright/test";
import * as fs from "node:fs";
import { readState } from "./stack.ts";

const st = readState();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
for (const route of process.argv.slice(2)) {
  await page.goto(st.webURL + route);
  await page.waitForTimeout(2500);
  const name = route.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "root";
  fs.writeFileSync(`artifacts/aria/${name}.yml`, await page.locator("body").ariaSnapshot());
  console.log(name);
}
await browser.close();
