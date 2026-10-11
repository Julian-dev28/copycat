/**
 * The copycat glossary (UX_AUDIT.md Top 10 #6). One noun per idea, used by
 * every page, so "wallet" never means two things on one screen.
 *
 * - Account: your own Hyperliquid account (what the Accounts dialog manages).
 * - Trader:  someone else's Hyperliquid address that you can copy.
 * - Copy:    a trader you copy (your copies; a trader you copy is "Copying").
 *
 * Never in UI copy: "leader" (say trader), "book" (say copies, or positions
 * for a trader's open positions). The api keeps its own field names
 * (`leaders`, `leader`, `in_book`); those are code, not copy.
 * src/lib/labels.test.ts and src/lib/copyTerms.test.ts enforce this.
 *
 * "Wallet" stays only for a browser wallet (MetaMask, Rabby) that signs.
 */

export const TERMS = {
  account: { one: "account", many: "accounts", One: "Account", Many: "Accounts" },
  trader: { one: "trader", many: "traders", One: "Trader", Many: "Traders" },
  copy: { one: "copy", many: "copies", One: "Copy", Many: "Copies" },
} as const;

export const LABELS = {
  // navigation and shell
  nav: { trade: "Trade", scout: "Scout", portfolio: "Portfolio", account: "Account", settings: "Settings" },
  accountsButton: "Accounts",
  accountsDialogTitle: "Accounts",
  accountMenu: "Account menu",
  manageAccounts: "Manage accounts",
  apiToken: "API token",
  noApiToken: "No API token set",
  apiTokenSet: "API token set",

  // copies (your copied traders)
  yourCopies: "Your copies",
  copying: "Copying",
  copyTrader: "Copy trader",
  stopCopying: "Stop copying",
  addToCopies: "Copy this trader",
  copiesFull: (max: number) => `You copy ${max} traders, the most allowed. Stop one to add another.`,
  copiesCount: (n: number, max: number) => `${n}/${max} copies`,
  noCopies: "No copies yet",

  // traders
  trader: "Trader",
  traders: "Traders",
  traderAddress: "Trader address",
  traderPositions: "Their positions",
  matchTrader: "Match trader",

  // settings scope
  globalDefault: "Global default",
  perTraderOverride: "Override for this trader",

  // demo
  demo: "Demo",
  leaveDemo: "Leave demo",
  demoStrip: "Sample data in this tab only. Nothing here reaches your account.",
} as const;

/** "1 copy", "3 copies"; "1 trader", "2 traders". */
export function countOf(n: number, term: keyof typeof TERMS): string {
  const t = TERMS[term];
  return `${n} ${n === 1 ? t.one : t.many}`;
}

/** Words that must not appear in user-visible copy, with what to say instead. */
export const BANNED_UI_WORDS: Record<string, string> = {
  leader: "trader",
  leaders: "traders",
  book: "copies (yours) or positions (a trader's)",
  books: "copies",
};
