import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createToastStore, TOAST_DURATION_MS, TOAST_MAX } from "./toastStore";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const make = () => createToastStore({ set: setTimeout, clear: clearTimeout });

describe("toast store", () => {
  it("queues newest last and notifies", () => {
    const s = make();
    const seen: number[] = [];
    s.subscribe(() => seen.push(s.get().length));
    s.show({ tone: "info", message: "a" });
    s.show({ tone: "success", message: "b" });
    expect(s.get().map((t) => t.message)).toEqual(["a", "b"]);
    expect(seen).toEqual([1, 2]);
  });

  it("caps the visible queue, dropping the oldest", () => {
    const s = make();
    for (let i = 0; i < TOAST_MAX + 2; i++) s.show({ tone: "info", message: String(i) });
    expect(s.get().map((t) => t.message)).toEqual(["2", "3", "4"]);
  });

  it("auto-dismisses after 5s (errors stay twice as long)", () => {
    const s = make();
    s.show({ tone: "info", message: "a" });
    s.show({ tone: "error", message: "e" });
    vi.advanceTimersByTime(TOAST_DURATION_MS);
    expect(s.get().map((t) => t.message)).toEqual(["e"]);
    vi.advanceTimersByTime(TOAST_DURATION_MS);
    expect(s.get()).toEqual([]);
  });

  it("dismisses on demand", () => {
    const s = make();
    const id = s.show({ tone: "info", message: "a", duration: 0 });
    s.dismiss(id);
    expect(s.get()).toEqual([]);
  });

  it("pauses while hovered and resumes with the time left", () => {
    const s = make();
    const id = s.show({ tone: "info", message: "a" });
    vi.advanceTimersByTime(3000);
    s.pause(id);
    vi.advanceTimersByTime(60_000);
    expect(s.get()).toHaveLength(1);
    s.resume(id);
    vi.advanceTimersByTime(1999);
    expect(s.get()).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(s.get()).toHaveLength(0);
  });

  it("duration 0 sticks until dismissed", () => {
    const s = make();
    s.show({ tone: "info", message: "a", duration: 0 });
    vi.advanceTimersByTime(60_000);
    expect(s.get()).toHaveLength(1);
  });
});
