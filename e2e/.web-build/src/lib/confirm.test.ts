import { describe, expect, it } from "vitest";
import { CLOSE_ALL_PHRASE, closeAllConfirmed } from "./confirm";

describe("closeAllConfirmed", () => {
  it("accepts exactly CLOSE", () => {
    expect(CLOSE_ALL_PHRASE).toBe("CLOSE");
    expect(closeAllConfirmed("CLOSE")).toBe(true);
  });

  it.each(["", "close", "Close", " CLOSE", "CLOSE ", "CLOS", "CLOSED"])("rejects %j", (typed) => {
    expect(closeAllConfirmed(typed)).toBe(false);
  });
});
