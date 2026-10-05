/**
 * `?demo=1` account source: an in-memory store with the same rules the api
 * enforces (passphrase length, signature must recover to the main address,
 * agent key must match the approved agent), so the demo exercises the real
 * flows end to end. Nothing here persists past a reload.
 */
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { recoverTypedDataAddress } from "viem";
import { ApiError } from "@/lib/api/client";
import { isValidAddress, normAddr } from "@/lib/address";
import { demoNowMs } from "@/lib/scout/api";
import type { AccountSource } from "./api";
import { fakeWalletProvider, setDemoDepositListener, type DemoWalletMode } from "./demoWallet";
import { fixtureAccounts, fixtureHistory, fixtureSummary } from "./fixtures";
import { actionProblem, emptyForm, unitsToUsd } from "./funding";
import { approveAgentTypedData, userActionTypedData } from "./typedData";
import type { AccountSummary, FundingInfo, TradingAccount, UserActionKind, UserActionPrepareRequest, UserActionResult } from "./types";

const DAY = 86_400_000;
const KEY_RE = /^0x[0-9a-fA-F]{64}$/;
let latency = 1;
const later = <T>(v: T, ms = 250) => new Promise<T>((r) => setTimeout(() => r(v), ms * latency));

/** Tests set 0 so the store answers on the next tick. */
export function setDemoLatency(scale: number): void {
  latency = scale;
}
const bad = (msg: string) => new ApiError(422, msg);

let store: TradingAccount[] | null = null;
const unfunded = new Set<string>();
let walletMode: DemoWalletMode = "approve";
let seq = 0;

function db(): TradingAccount[] {
  if (!store) store = fixtureAccounts(demoNowMs());
  return store;
}

function find(id: string): TradingAccount {
  const a = db().find((x) => x.id === id);
  if (!a) throw new ApiError(404, "no account with that id");
  return a;
}

function upsert(next: TradingAccount): TradingAccount {
  const list = db();
  const i = list.findIndex((a) => a.address === next.address);
  if (i >= 0) {
    list[i] = { ...list[i], ...next, id: list[i].id, label: next.label || list[i].label, active: list[i].active };
    return list[i];
  }
  list.push(next);
  return next;
}

function agentFields(agentAddress: string, name: string | null) {
  return { agent_address: agentAddress.toLowerCase(), agent_name: name, agent_valid_until_ms: demoNowMs() + 180 * DAY, agent_status: "active" as const };
}

/** Test/QA hook: reset to the three fixture accounts (or none). */
export function resetDemoAccounts(empty = false): void {
  store = empty ? [] : fixtureAccounts(demoNowMs());
  unfunded.clear();
  deltas.clear();
}

// ── funding (demo) ─────────────────────────────────────────────────────────────
// Balance changes from demo deposits / moves / sends / withdrawals, per account id.
const deltas = new Map<string, { perps: number; spot: number }>();
/** The operator's real situation: $0.03 perps, $0.11 spot USDC, so "Move to perps" shows. */
const SMALL = "acc_ledger";
/** A unified account: spot and perps share one balance, nothing to move. */
const UNIFIED = "acc_api";
const r6 = (n: number) => Math.round(n * 1e6) / 1e6;

function bump(id: string, perps: number, spot: number): void {
  const d = deltas.get(id) ?? { perps: 0, spot: 0 };
  deltas.set(id, { perps: r6(d.perps + perps), spot: r6(d.spot + spot) });
}

function withDeltas(s: AccountSummary): AccountSummary {
  const base = s.account.id === SMALL
    ? { ...s.balances, perps_usd: 0.03, spot_usd: 0.11, staked_usd: 0, copytrade_usd: 0, total_usd: 0.14, withdrawable_usd: 0.03 }
    : s.balances;
  const d = deltas.get(s.account.id) ?? { perps: 0, spot: 0 };
  const b = {
    ...base, perps_usd: r6(base.perps_usd + d.perps), spot_usd: r6(base.spot_usd + d.spot),
    total_usd: r6(base.total_usd + d.perps + d.spot), withdrawable_usd: r6(Math.max(0, base.withdrawable_usd + d.perps)),
  };
  return { ...s, balances: b };
}

const demoSummary = (a: TradingAccount) => withDeltas(fixtureSummary({ ...a }, demoNowMs(), !unfunded.has(a.id)));

setDemoDepositListener((from, units) => {
  const a = db().find((x) => x.address === from);
  if (!a) return;
  // Hyperliquid credits a bridge deposit within ~1 minute; the demo takes a few seconds
  setTimeout(() => {
    unfunded.delete(a.id);
    bump(a.id, unitsToUsd(units), 0);
  }, 3000 * latency);
});

function demoFundingInfo(a: TradingAccount): FundingInfo {
  const b = demoSummary(a).balances;
  const unified = a.id === UNIFIED;
  return {
    network: "mainnet", chain_id: 42161, chain_name: "Arbitrum One",
    usdc_address: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", bridge_address: "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7",
    explorer_url: "https://arbiscan.io", min_deposit_usd: 5, withdraw_fee_usd: 1, account_address: a.address, account_kind: a.kind,
    signer: a.kind === "created" && a.has_main_key ? "passphrase" : "browser",
    limits: { abstraction: unified ? "unifiedAccount" : "default", unified, perps_withdrawable_usd: b.withdrawable_usd, spot_usdc_free_usd: Math.max(0, b.spot_usd) },
    source_url: "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/usdc",
    notes: ["Demo data: nothing here touches Arbitrum or Hyperliquid."],
  };
}

const amountText = (n: number) => String(Math.floor(n * 1e6 + 1e-6) / 1e6);

function guard(a: TradingAccount, req: UserActionPrepareRequest): string {
  const info = demoFundingInfo(a);
  const form = { ...emptyForm(Boolean(req.to_perp)), amount: amountText(req.amount_usd), destination: req.destination ?? "", confirm: req.confirm_destination ?? "" };
  const others = db().filter((x) => x.id !== a.id).map((x) => x.address);
  const problem = actionProblem(req.kind, form, { limits: info.limits, feeUsd: info.withdraw_fee_usd, own: a.address, others, needsPassphrase: false });
  if (problem) throw new ApiError(400, problem);
  return req.kind === "usd_send" || (req.kind === "withdraw" && req.destination) ? normAddr(req.destination ?? "") : req.kind === "withdraw" ? a.address : "";
}

function apply(a: TradingAccount, kind: UserActionKind, amount: number, toPerp: boolean | null, dest: string, nonce: number): UserActionResult {
  if (kind === "usd_class_transfer") bump(a.id, toPerp ? amount : -amount, toPerp ? -amount : amount);
  else bump(a.id, -amount, 0);
  if (kind === "usd_send") {
    const to = db().find((x) => x.address === dest);
    if (to) bump(to.id, amount, 0);
  }
  const message = kind === "usd_class_transfer" ? `Moved ${amount} USDC ${toPerp ? "spot -> perps" : "perps -> spot"}.`
    : kind === "usd_send" ? `Sent ${amount} USDC to ${dest}.` : `Withdrawal of ${amount} USDC to ${dest} on Arbitrum requested (fee 1 USDC, arrives in about 5 minutes).`;
  return { ok: true, kind, account_address: a.address, amount_usd: amount, to_perp: kind === "usd_class_transfer" ? toPerp : null, destination: dest || null, fee_usd: kind === "withdraw" ? 1 : null, nonce, message };
}

export function setDemoWalletMode(mode: DemoWalletMode): void {
  walletMode = mode;
}

export const demoAccounts: AccountSource = {
  list: () => later(db().map((a) => ({ ...a }))),
  create: async ({ label, passphrase }) => {
    if (passphrase.length < 12) throw bad("passphrase must be at least 12 characters");
    const key = generatePrivateKey();
    const account: TradingAccount = {
      id: `acc_demo_${++seq}`, label: label.trim(), kind: "created", address: privateKeyToAccount(key).address.toLowerCase(),
      agent_status: "missing", active: false, created_ms: demoNowMs(), has_main_key: true,
    };
    db().push(account);
    unfunded.add(account.id);
    return later({ account: { ...account }, private_key: key, backup_warning: "This is the only time copycat shows this key. Lose it and the passphrase, and the funds are gone." }, 700);
  },
  importKey: async ({ label, main_address, agent_private_key }) => {
    if (!isValidAddress(main_address)) throw bad("main_address is not a 0x address");
    if (!KEY_RE.test(agent_private_key)) throw bad("the API wallet key must be 0x followed by 64 hex characters");
    const agent = privateKeyToAccount(agent_private_key as `0x${string}`).address;
    return later(upsert({ id: `acc_demo_${++seq}`, label: label.trim(), kind: "connected_key", address: normAddr(main_address), ...agentFields(agent, null), active: false, created_ms: demoNowMs(), has_main_key: false }), 500);
  },
  importEnvStatus: async () =>
    later(db().length ? { available: false, reason: "accounts already exist" } : { available: true, address: fixtureAccounts(demoNowMs())[0].address }),
  importEnv: async () => {
    if (db().length) throw new ApiError(409, "accounts already exist; import from .env only works on an empty list");
    const a: TradingAccount = { ...fixtureAccounts(demoNowMs())[0], id: "acc_env", label: "From .env", kind: "connected_key", has_main_key: false, active: true };
    db().push(a);
    return later([{ ...a }], 400);
  },
  prepare: async ({ main_address, agent_address, agent_name }) => {
    if (!isValidAddress(main_address) || !isValidAddress(agent_address)) throw bad("addresses must be 0x addresses");
    const nonce = demoNowMs() + ++seq;
    return later(approveAgentTypedData(agent_address, agent_name ?? "copycat", nonce, "Mainnet"), 300);
  },
  submit: async ({ label, main_address, agent_private_key, action, nonce, signature }) => {
    const agentAddress = String(action.agentAddress ?? "");
    const { typed_data } = approveAgentTypedData(agentAddress, String(action.agentName ?? "copycat"), nonce, "Mainnet");
    const signer = await recoverTypedDataAddress({ ...(typed_data as Parameters<typeof recoverTypedDataAddress>[0]), signature: signature as `0x${string}` });
    if (normAddr(signer) !== normAddr(main_address)) throw bad("the signature was not made by the main address");
    if (!KEY_RE.test(agent_private_key) || normAddr(privateKeyToAccount(agent_private_key as `0x${string}`).address) !== normAddr(agentAddress)) {
      throw bad("the agent key does not match the approved agent");
    }
    return later(upsert({ id: `acc_demo_${++seq}`, label: label.trim(), kind: "connected_signed", address: normAddr(main_address), ...agentFields(agentAddress, "copycat"), active: false, created_ms: demoNowMs(), has_main_key: false }), 500);
  },
  activate: async (id, force = false) => {
    find(id);
    const current = db().find((a) => a.active);
    // demo: the fixture "Main" account has copies open, like a live engine would
    if (!force && current && current.id !== id && current.id === "acc_main") {
      throw new ApiError(409, `${current.address} still has 3 copies open. Close them first (Close all), or activate with force=true to leave them unmanaged.`);
    }
    for (const a of db()) a.active = a.id === id;
    await later(null);
  },
  rename: async (id, label) => {
    if (!label.trim()) throw bad("label is empty");
    find(id).label = label.trim();
    await later(null);
  },
  remove: async (id) => {
    find(id);
    store = db().filter((a) => a.id !== id);
    await later(null);
  },
  refreshAgent: async (id, passphrase) => {
    const a = find(id);
    if (a.kind === "connected_key") throw bad("API-key accounts refresh by importing a new key");
    if (a.kind === "created" && (!passphrase || passphrase.length < 12)) throw new ApiError(401, "invalid passphrase");
    if (a.kind === "created") unfunded.delete(a.id); // demo: pretend the deposit landed
    Object.assign(a, agentFields(`0x${"ca7".repeat(13)}a`, "copycat"));
    await later(null, 600);
  },
  transfer: async ({ from_account_id, to_address, amount_usd, passphrase }) => {
    if (!find(from_account_id).has_main_key) throw bad("only copycat-created accounts can send");
    if (!isValidAddress(to_address)) throw bad("to_address is not a 0x address");
    if (!(amount_usd > 0)) throw bad("amount must be positive");
    if (passphrase.length < 12) throw new ApiError(401, "invalid passphrase");
    await later(null, 700);
  },
  summary: async (id) => {
    const a = find(id);
    const s = demoSummary(a);
    // accounts added this session: balances yes, discovery metrics not yet (the live api's state too)
    if (a.id.startsWith("acc_demo_") && !unfunded.has(a.id)) {
      return later({ ...s, risk_30d: null, trades_30d: null, style: null, avg_hold_h: null, median_hold_h: null, pnl_tier: null, size_tier: null, longest_win_streak_days: null, daily_pnl: [] });
    }
    return later(s);
  },
  history: async (id, kind) => {
    const a = find(id);
    return later(fixtureHistory(a, kind, demoNowMs(), !unfunded.has(a.id)));
  },
  fundingInfo: async (id) => later(demoFundingInfo(find(id))),
  prepareAction: async (id, req) => {
    const a = find(id);
    const dest = guard(a, req);
    const nonce = demoNowMs() + ++seq;
    return later(userActionTypedData(req.kind, amountText(req.amount_usd), nonce, { toPerp: req.to_perp, destination: dest }, "Mainnet"), 300);
  },
  submitAction: async (id, { kind, action, nonce, signature, confirm_destination }) => {
    const a = find(id);
    const amount = Number(action.amount);
    const toPerp = kind === "usd_class_transfer" ? Boolean(action.toPerp) : null;
    const dest = guard(a, { kind, amount_usd: amount, to_perp: toPerp, destination: kind === "usd_class_transfer" ? null : String(action.destination), confirm_destination });
    const { typed_data } = userActionTypedData(kind, String(action.amount), nonce, { toPerp, destination: dest }, "Mainnet");
    const signer = await recoverTypedDataAddress({ ...(typed_data as Parameters<typeof recoverTypedDataAddress>[0]), signature: signature as `0x${string}` });
    if (normAddr(signer) !== a.address) throw bad(`the signature was not made by ${a.address}. Sign with that wallet.`);
    return later(apply(a, kind, amount, toPerp, dest, nonce), 500);
  },
  runAction: async (id, { passphrase, ...req }) => {
    const a = find(id);
    if (a.kind !== "created" || !a.has_main_key) throw new ApiError(400, "only a wallet copycat created can be signed with the passphrase");
    const dest = guard(a, req);
    if (passphrase.length < 12) throw new ApiError(401, "invalid passphrase");
    return later(apply(a, req.kind, Number(amountText(req.amount_usd)), req.kind === "usd_class_transfer" ? Boolean(req.to_perp) : null, dest, demoNowMs()), 700);
  },
  walletProvider: () => fakeWalletProvider(walletMode),
};
