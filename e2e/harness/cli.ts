/**
 * Keep a throwaway stack running for debugging a test by hand:
 *   node harness/cli.ts up [web|full]   (prints the URLs; state in e2e/.stack.json)
 *   node harness/cli.ts down
 */
import { startStack, stopStack } from "./stack.ts";

const [cmd, mode] = process.argv.slice(2);
if (cmd === "up") {
  stopStack();
  const st = await startStack(mode === "full" ? "full" : "web");
  console.log(JSON.stringify({ web: st.webURL, api: st.apiURL, mock: st.mockURL, token: st.token, root: st.root }, null, 2));
} else if (cmd === "down") {
  stopStack();
} else {
  console.error("usage: node harness/cli.ts up [web|full] | down");
  process.exit(2);
}
