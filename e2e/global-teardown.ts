import { stopStack } from "./harness/stack";

export default async function globalTeardown() {
  stopStack();
}
