/**
 * Passphrase rules for created wallets. The api enforces min 12 / max 256
 * (CreateAccountRequest); this mirrors it so the form says why before the
 * round trip, and adds a strength hint. Pure.
 */

export const PASSPHRASE_MIN = 12;
export const PASSPHRASE_MAX = 256;

export type Strength = "too_short" | "weak" | "fair" | "strong";

export const STRENGTH_META: Record<Strength, { label: string; hint: string; bars: number }> = {
  too_short: { label: "Too short", hint: `At least ${PASSPHRASE_MIN} characters.`, bars: 0 },
  weak: { label: "Weak", hint: "Repeats or uses one kind of character. Try four unrelated words.", bars: 1 },
  fair: { label: "Fair", hint: "Okay. A few more words make it much harder to guess.", bars: 2 },
  strong: { label: "Strong", hint: "Good. Store it somewhere safe: nobody can reset it.", bars: 3 },
};

/**
 * Rough entropy estimate: character pool size times length, with repeats
 * penalized. Not zxcvbn, but it tells "aaaaaaaaaaaa" from a passphrase.
 */
export function passphraseStrength(p: string): Strength {
  if (p.length < PASSPHRASE_MIN) return "too_short";
  let pool = 0;
  if (/[a-z]/.test(p)) pool += 26;
  if (/[A-Z]/.test(p)) pool += 26;
  if (/[0-9]/.test(p)) pool += 10;
  if (/[^a-zA-Z0-9]/.test(p)) pool += 20;
  const unique = new Set(p).size;
  const effectiveLen = Math.min(p.length, unique * 2);
  const bits = effectiveLen * Math.log2(Math.max(pool, 2));
  if (unique < 5 || bits < 60) return "weak";
  if (bits < 90) return "fair";
  return "strong";
}

export interface PassphraseCheck {
  ok: boolean;
  error: string | null;
}

export function checkPassphrase(p: string, confirm: string): PassphraseCheck {
  if (p.length < PASSPHRASE_MIN) return { ok: false, error: `Use at least ${PASSPHRASE_MIN} characters.` };
  if (p.length > PASSPHRASE_MAX) return { ok: false, error: `Keep it under ${PASSPHRASE_MAX} characters.` };
  if (p !== confirm) return { ok: false, error: "The two passphrases do not match." };
  return { ok: true, error: null };
}

export const LABEL_MAX = 60;

export function checkLabel(label: string): string | null {
  const t = label.trim();
  if (!t) return "Give it a name.";
  if (t.length > LABEL_MAX) return `Keep the name under ${LABEL_MAX} characters.`;
  return null;
}
