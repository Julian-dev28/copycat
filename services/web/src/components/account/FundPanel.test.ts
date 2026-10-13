import { describe, expect, it } from "vitest";
import { STEPS } from "./FundPanel";

describe("FundPanel deposit steps", () => {
  it("states Hyperliquid's sender-crediting rule for the Arbitrum step", () => {
    const arbitrumStep = STEPS.find((s) => s.startsWith("From Arbitrum"));
    expect(arbitrumStep).toBeDefined();
    expect(arbitrumStep).toMatch(/credits whichever address sends/);
  });

  it("never tells the user to send straight to this address and then warns against exactly that", () => {
    // Regression: the old copy said "use Deposit, which sends USDC... from
    // this address" immediately followed by "Never send USDC on Arbitrum
    // straight to this address: it stays on Arbitrum" - the same action,
    // described as both the instructed step and the thing never to do.
    const arbitrumStep = STEPS.find((s) => s.startsWith("From Arbitrum"))!;
    expect(arbitrumStep).not.toMatch(/use Deposit, which sends USDC to Hyperliquid's bridge from this address/);
  });

  it("tells exchange withdrawals to use the Hyperliquid network, not Arbitrum", () => {
    const exchangeStep = STEPS.find((s) => s.startsWith("From an exchange"));
    expect(exchangeStep).toMatch(/Hyperliquid network \(not Arbitrum\)/);
  });
});
