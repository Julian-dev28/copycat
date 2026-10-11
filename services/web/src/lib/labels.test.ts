import { describe, expect, it } from "vitest";
import { BANNED_COPY } from "./copyScan";
import { BANNED_UI_WORDS, countOf, LABELS, TERMS } from "./labels";

/** Every string the glossary exports, including the output of its functions. */
function allLabelStrings(): string[] {
  const out: string[] = [];
  const visit = (v: unknown) => {
    if (typeof v === "string") out.push(v);
    else if (typeof v === "function") out.push(String((v as (...a: number[]) => string)(3, 25)));
    else if (v && typeof v === "object") Object.values(v).forEach(visit);
  };
  visit(LABELS);
  visit(TERMS);
  return out;
}

describe("labels glossary", () => {
  it("uses one noun per idea: Account, Trader, Copies", () => {
    expect(TERMS.account.Many).toBe("Accounts");
    expect(TERMS.trader.One).toBe("Trader");
    expect(TERMS.copy.Many).toBe("Copies");
    expect(LABELS.accountsButton).toBe("Accounts");
    expect(LABELS.accountsDialogTitle).toBe("Accounts");
    expect(LABELS.yourCopies).toBe("Your copies");
    expect(LABELS.copying).toBe("Copying");
  });

  it("never uses a banned word itself", () => {
    const strings = allLabelStrings();
    expect(strings.length).toBeGreaterThan(20);
    expect(strings.filter((s) => BANNED_COPY.test(s))).toEqual([]);
  });

  it("never calls your account or a trader a wallet", () => {
    expect(allLabelStrings().filter((s) => /\bwallets?\b/i.test(s))).toEqual([]);
  });

  it("names a replacement for every banned word", () => {
    for (const w of ["leader", "leaders", "book", "books"]) expect(BANNED_UI_WORDS[w]).toBeTruthy();
    expect(BANNED_UI_WORDS.leader).toBe("trader");
  });

  it("pluralizes counts", () => {
    expect(countOf(1, "copy")).toBe("1 copy");
    expect(countOf(3, "copy")).toBe("3 copies");
    expect(countOf(0, "trader")).toBe("0 traders");
    expect(countOf(1, "account")).toBe("1 account");
  });

  it("formats the copy cap", () => {
    expect(LABELS.copiesCount(3, 25)).toBe("3/25 copies");
    expect(LABELS.copiesFull(25)).toContain("25 traders");
  });
});
