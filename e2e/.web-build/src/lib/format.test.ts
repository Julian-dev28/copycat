import { describe, expect, it } from "vitest";
import { formatAgo, formatPrice, formatSignedPct, formatSize, formatUsd, shortenAddress } from "./format";

describe("formatPrice", () => {
  it("keeps 2 decimals at or above $1", () => {
    expect(formatPrice(97123.456)).toBe("$97,123.46");
    expect(formatPrice(1)).toBe("$1.00");
  });

  it("keeps significant digits for sub-dollar coins instead of printing $0.00", () => {
    expect(formatPrice(0.000012345)).toBe("$0.000012345");
    expect(formatPrice(0.0123456789)).toBe("$0.012346");
  });

  it("handles zero, negatives and missing values", () => {
    expect(formatPrice(0)).toBe("$0");
    expect(formatPrice(-2.5)).toBe("$-2.50");
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(Number.NaN)).toBe("—");
  });
});

describe("formatSize", () => {
  it("drops float noise and the sign (side is shown separately)", () => {
    expect(formatSize(0.30000000000000004)).toBe("0.3");
    expect(formatSize(-1234.5678)).toBe("1,234.57");
  });
});

describe("existing formatters", () => {
  it("formatUsd compact and plain", () => {
    expect(formatUsd(764365.249)).toBe("$764,365.25");
    expect(formatUsd(1_250_000, true)).toBe("$1.3M");
  });

  it("formatSignedPct adds a + only for positive values", () => {
    expect(formatSignedPct(12.34)).toBe("+12.3%");
    expect(formatSignedPct(-1)).toBe("-1.0%");
    expect(formatSignedPct(0)).toBe("0.0%");
  });

  it("shortenAddress keeps head and tail", () => {
    expect(shortenAddress("0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa")).toBe("0x04a9…95aa");
  });

  it("formatAgo buckets", () => {
    expect(formatAgo(1000, 1000)).toBe("just now");
    expect(formatAgo(0, 30_000)).toBe("30s ago");
    expect(formatAgo(0, 5 * 60_000)).toBe("5m ago");
  });
});
