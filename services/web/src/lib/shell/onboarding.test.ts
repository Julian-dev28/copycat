import { describe, expect, it } from "vitest";
import { onboardingComplete, onboardingSteps, type OnboardingState } from "./onboarding";

const DONE: OnboardingState = {
  hasToken: true, hasActiveAccount: true, equityUsd: 25, walletsInBook: 1, tradingLive: true,
};

describe("onboardingSteps", () => {
  it("is all done once every real signal is true", () => {
    const steps = onboardingSteps(DONE);
    expect(steps.every((s) => s.done)).toBe(true);
    expect(onboardingComplete(steps)).toBe(true);
  });

  it("marks each step independently from real state, not a simulated sequence", () => {
    // A wallet picked and trading live, but equity read as 0 (e.g. a withdrawal):
    // deposit must flip back to not-done even though later steps look done.
    const steps = onboardingSteps({ ...DONE, equityUsd: 0 });
    const byKey = Object.fromEntries(steps.map((s) => [s.key, s]));
    expect(byKey.deposit.done).toBe(false);
    expect(byKey.wallet.done).toBe(true);
    expect(byKey.live.done).toBe(true);
    expect(onboardingComplete(steps)).toBe(false);
  });

  it("never counts unknown equity (null, not loaded yet) as funded", () => {
    const steps = onboardingSteps({ ...DONE, equityUsd: null });
    expect(steps.find((s) => s.key === "deposit")?.done).toBe(false);
  });

  it("the token step has no href: it opens the drawer, not a page", () => {
    expect(onboardingSteps(DONE).find((s) => s.key === "token")?.href).toBeNull();
  });

  it("starts with nothing done when every signal is false/zero", () => {
    const steps = onboardingSteps({ hasToken: false, hasActiveAccount: false, equityUsd: null, walletsInBook: 0, tradingLive: false });
    expect(steps.every((s) => !s.done)).toBe(true);
    expect(onboardingComplete(steps)).toBe(false);
  });
});
