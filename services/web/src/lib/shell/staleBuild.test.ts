import { describe, expect, it } from "vitest";
import { CONTRACT_VERSION } from "@/lib/api/types";
import { staleBuildText } from "./staleBuild";

const h = (stale: string[], cv = CONTRACT_VERSION) => ({ stale, contract_version: cv });

describe("staleBuildText", () => {
  it("is null when every process runs the api's code", () => {
    expect(staleBuildText(h([]))).toBeNull();
    expect(staleBuildText(undefined)).toBeNull();
  });
  it("names the stale processes, engine first", () => {
    expect(staleBuildText(h(["scout", "engine"]))).toMatch(/^The engine and scout are running older code/);
    expect(staleBuildText(h(["scout"]))).toMatch(/Restart it/);
  });
  it("asks for a reload when the api's contract is newer than this page", () => {
    expect(staleBuildText(h([], CONTRACT_VERSION + 1))).toMatch(/Reload it/);
  });
});
