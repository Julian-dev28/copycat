import { describe, expect, it } from "vitest";
import { longShortSplit } from "./split";

describe("longShortSplit", () => {
  it("shares out the trips and rounds the long side", () => {
    expect(longShortSplit({ long_trips: 2, short_trips: 6 })).toEqual({ long: 2, short: 6, longPct: 25 });
    expect(longShortSplit({ long_trips: 1, short_trips: 2 })?.longPct).toBe(33);
  });
  it("is null with no trips", () => {
    expect(longShortSplit({ long_trips: 0, short_trips: 0 })).toBeNull();
    expect(longShortSplit(null)).toBeNull();
  });
});
