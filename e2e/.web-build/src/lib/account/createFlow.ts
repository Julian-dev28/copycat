/**
 * The create-wallet dialog as a reducer: form -> reveal (key shown once)
 * -> fund. The private key only ever lives in `reveal.privateKey`, and
 * every way out of the reveal step drops it:
 *   - "saved"  (user ticked "I saved my key" and continued) -> fund, key gone
 *   - "close"  (dialog closed)                             -> initial, key gone
 * A close while the key is unsaved is refused (the dialog stays open), so
 * the user cannot lose the only copy by hitting Esc.
 */
import type { CreateAccountResponse, TradingAccount } from "./types";

export type CreateState =
  | { step: "form" }
  | { step: "reveal"; account: TradingAccount; privateKey: string; warning: string; revealed: boolean; saved: boolean }
  | { step: "fund"; account: TradingAccount };

export type CreateEvent =
  | { type: "created"; res: CreateAccountResponse }
  | { type: "reveal" }
  | { type: "toggleSaved"; saved: boolean }
  | { type: "continue" }
  | { type: "close" };

export const initialCreate: CreateState = { step: "form" };

export function createReducer(s: CreateState, e: CreateEvent): CreateState {
  switch (e.type) {
    case "created":
      return { step: "reveal", account: e.res.account, privateKey: e.res.private_key, warning: e.res.backup_warning, revealed: false, saved: false };
    case "reveal":
      return s.step === "reveal" ? { ...s, revealed: true } : s;
    case "toggleSaved":
      return s.step === "reveal" ? { ...s, saved: e.saved } : s;
    case "continue":
      return s.step === "reveal" && s.saved ? { step: "fund", account: s.account } : s;
    case "close":
      return canClose(s) ? initialCreate : s;
  }
}

/** The dialog may close unless an unsaved key is on screen. */
export function canClose(s: CreateState): boolean {
  return s.step !== "reveal" || s.saved;
}

/** True when the state holds the plaintext key (for tests and a debug assert). */
export function holdsKey(s: CreateState): boolean {
  return s.step === "reveal" && s.privateKey.length > 0;
}
