import { startStack, stopStack } from "./harness/stack";

export default async function globalSetup() {
  stopStack(); // a crashed earlier run may have left processes behind
  const st = await startStack(process.env.E2E_STACK === "full" ? "full" : "web");
  process.env.E2E_WEB_URL = st.webURL;
}
