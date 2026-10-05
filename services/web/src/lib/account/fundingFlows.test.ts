/**
 * Deposit and Move/Send/Withdraw state machines, end to end against the demo
 * store + the scripted wallet (real EIP-712 signatures, real ERC-20 calldata).
 */
import { beforeEach, describe, expect, it } from "vitest";
import { actionReducer, initialAction, runAction, type ActionDeps, type ActionState } from "./actionFlow";
import { demoAccounts, resetDemoAccounts, setDemoLatency } from "./demo";
import { connectDeposit, depositReducer, initialDeposit, sendDeposit, type DepositDeps, type DepositState } from "./depositFlow";
import { DEMO_WALLET_ADDRESS, fakeWalletProvider, type DemoWalletMode } from "./demoWallet";
import type { Eip1193Provider } from "./eip1193";
import type { FundingInfo, UserActionPrepareRequest } from "./types";

beforeEach(() => {
  setDemoLatency(0);
  resetDemoAccounts();
});

const tick = () => new Promise((r) => setTimeout(r, 5));

async function info(id: string): Promise<FundingInfo> {
  return demoAccounts.fundingInfo(id);
}

function recorder<S, E>(reducer: (s: S, e: E) => S, init: S) {
  const box = { s: init, steps: [] as string[] };
  return { box, dispatch: (e: E) => { box.s = reducer(box.s, e); box.steps.push((box.s as { step: string }).step); } };
}

async function deposit(mode: DemoWalletMode, amount: string, accountId = "acc_ledger", provider?: Eip1193Provider | null) {
  const deps: DepositDeps = { provider: provider === undefined ? fakeWalletProvider(mode, 0) : provider, info: await info(accountId), pollMs: 0, sleep: async () => {} };
  const { box, dispatch } = recorder<DepositState, Parameters<typeof depositReducer>[1]>(depositReducer, initialDeposit);
  const ok = await connectDeposit(deps, dispatch);
  const hash = ok ? await sendDeposit(deps, amount, box.s.balanceUsd, dispatch) : null;
  return { s: box.s, steps: box.steps, hash };
}

describe("deposit from Arbitrum", () => {
  it("connects, switches to Arbitrum, reads the balance, sends, waits for the receipt", async () => {
    const before = (await demoAccounts.summary("acc_ledger")).balances.perps_usd;
    const { s, steps, hash } = await deposit("approve", "25");
    expect(steps).toEqual(expect.arrayContaining(["connecting", "switching", "reading", "ready", "confirming", "pending", "confirmed"]));
    expect(s.step).toBe("confirmed");
    expect(s.balanceUsd).toBe(250);
    expect(hash).toMatch(/^0x[0-9a-f]{64}$/);
    await tick(); // the demo "bridge" credits the sender
    expect((await demoAccounts.summary("acc_ledger")).balances.perps_usd).toBeCloseTo(before + 25, 6);
  });

  it("blocks below the 5 USDC minimum: nothing is sent", async () => {
    const { s, steps } = await deposit("approve", "4.99");
    expect(s.step).toBe("error");
    expect(s.error?.kind).toBe("blocked");
    expect(s.error?.message).toMatch(/minimum deposit is 5 USDC/);
    expect(steps).not.toContain("confirming");
    expect(s.txHash).toBeNull();
  });

  it("blocks more than the wallet holds", async () => {
    const { s } = await deposit("approve", "251");
    expect(s.error?.message).toMatch(/only holds/);
    expect(s.txHash).toBeNull();
  });

  it("blocks a wallet that is not the account's own address (the bridge credits the sender)", async () => {
    const { s, steps } = await deposit("wrong_account", "25");
    expect(s.step).toBe("error");
    expect(s.error?.kind).toBe("wrong_account");
    expect(s.error?.message).toMatch(/must come from/);
    expect(steps).not.toContain("ready");
  });

  it("a created account cannot deposit from the demo browser wallet (different address)", async () => {
    const { s } = await deposit("approve", "25", "acc_main");
    expect(s.error?.kind).toBe("wrong_account");
  });

  it("a rejected transfer sends nothing", async () => {
    const base = fakeWalletProvider("approve", 0)!;
    const rejecting: Eip1193Provider = {
      request: (a) => (a.method === "eth_sendTransaction" ? Promise.reject(Object.assign(new Error("no"), { code: 4001 })) : base.request(a)),
    };
    const { s } = await deposit("approve", "25", "acc_ledger", rejecting);
    expect(s.error?.kind).toBe("rejected");
    expect(s.error?.message).toMatch(/Nothing was sent/);
  });

  it("a reverted transfer is reported, a missing receipt says check before resending", async () => {
    const base = fakeWalletProvider("approve", 0)!;
    const reverting: Eip1193Provider = {
      request: (a) => (a.method === "eth_getTransactionReceipt" ? Promise.resolve({ status: "0x0" }) : base.request(a)),
    };
    expect((await deposit("approve", "25", "acc_ledger", reverting)).s.error?.message).toMatch(/reverted/);
    const base2 = fakeWalletProvider("approve", 0)!;
    const silent: Eip1193Provider = { request: (a) => (a.method === "eth_getTransactionReceipt" ? Promise.resolve(null) : base2.request(a)) };
    const { s } = await deposit("approve", "25", "acc_ledger", silent);
    expect(s.error?.kind).toBe("pending");
    expect(s.error?.message).toMatch(/BEFORE sending again/);
    expect(s.txHash).not.toBeNull();
  });

  it("no wallet installed", async () => {
    const { s } = await deposit("none", "25", "acc_ledger", null);
    expect(s.error?.kind).toBe("no_wallet");
  });
});

function deps(path: ActionDeps["path"], accountId: string, own: string, mode: DemoWalletMode = "approve"): ActionDeps {
  return {
    path, accountId, own, provider: fakeWalletProvider(mode, 0),
    prepare: demoAccounts.prepareAction, submit: demoAccounts.submitAction, run: demoAccounts.runAction,
  };
}

async function act(d: ActionDeps, req: UserActionPrepareRequest, pass: string | null = null) {
  const { box, dispatch } = recorder<ActionState, Parameters<typeof actionReducer>[1]>(actionReducer, initialAction);
  const result = await runAction(d, req, pass, dispatch);
  return { s: box.s, steps: box.steps, result };
}

describe("move / send / withdraw", () => {
  it("browser: moves the $0.11 spot USDC to perps with a real signature", async () => {
    const { s, steps } = await act(deps("browser", "acc_ledger", DEMO_WALLET_ADDRESS), { kind: "usd_class_transfer", amount_usd: 0.11, to_perp: true });
    expect(s.step).toBe("done");
    expect(steps).toEqual(["connecting", "preparing", "switching", "signing", "submitting", "done"]);
    const b = (await demoAccounts.summary("acc_ledger")).balances;
    expect(b.perps_usd).toBeCloseTo(0.14, 6);
    expect(b.spot_usd).toBeCloseTo(0, 6);
  });

  it("browser: the wrong wallet is refused before anything is signed", async () => {
    const { s, steps } = await act(deps("browser", "acc_ledger", DEMO_WALLET_ADDRESS, "wrong_account"), { kind: "usd_class_transfer", amount_usd: 0.1, to_perp: true });
    expect(s.error?.kind).toBe("wrong_account");
    expect(steps).not.toContain("signing");
  });

  it("browser: a rejected signature moves nothing", async () => {
    const { s } = await act(deps("browser", "acc_ledger", DEMO_WALLET_ADDRESS, "reject_sign"), { kind: "usd_class_transfer", amount_usd: 0.1, to_perp: true });
    expect(s.error?.kind).toBe("rejected");
    expect((await demoAccounts.summary("acc_ledger")).balances.spot_usd).toBeCloseTo(0.11, 6);
  });

  it("the store refuses a signature from another key (signer mismatch)", async () => {
    const prep = await demoAccounts.prepareAction("acc_ledger", { kind: "usd_class_transfer", amount_usd: 0.1, to_perp: true });
    await expect(demoAccounts.submitAction("acc_ledger", { kind: "usd_class_transfer", action: prep.action, nonce: prep.nonce, signature: `0x${"ab".repeat(65)}` })).rejects.toThrow();
  });

  it("over the live limit is refused by the api, not signed", async () => {
    const { s, steps } = await act(deps("browser", "acc_ledger", DEMO_WALLET_ADDRESS), { kind: "usd_class_transfer", amount_usd: 5, to_perp: true });
    expect(s.error?.kind).toBe("api");
    expect(s.error?.message).toMatch(/At most/);
    expect(steps).not.toContain("signing");
  });

  it("passphrase: created account withdraws to its own address; wrong passphrase says so", async () => {
    const d = deps("passphrase", "acc_main", "");
    const bad = await act(d, { kind: "withdraw", amount_usd: 10 }, "short");
    expect(bad.s.error?.message).toMatch(/Wrong passphrase/);
    const { s, result } = await act(d, { kind: "withdraw", amount_usd: 10 }, "x".repeat(12));
    expect(s.step).toBe("done");
    expect(result?.fee_usd).toBe(1);
    expect(result?.destination).toBe((await demoAccounts.list()).find((a) => a.id === "acc_main")?.address);
  });

  it("withdraw to another address needs the typed confirm", async () => {
    const d = deps("passphrase", "acc_main", "");
    const other = `0x${"cc".repeat(20)}`;
    expect((await act(d, { kind: "withdraw", amount_usd: 10, destination: other }, "x".repeat(12))).s.error?.message).toMatch(/again in full/);
    expect((await act(d, { kind: "withdraw", amount_usd: 10, destination: other, confirm_destination: other }, "x".repeat(12))).s.step).toBe("done");
  });

  it("send goes to another of the user's accounts and credits it", async () => {
    const before = (await demoAccounts.summary("acc_ledger")).balances.perps_usd;
    const { s } = await act(deps("passphrase", "acc_main", ""), { kind: "usd_send", amount_usd: 7, destination: DEMO_WALLET_ADDRESS }, "x".repeat(12));
    expect(s.step).toBe("done");
    expect((await demoAccounts.summary("acc_ledger")).balances.perps_usd).toBeCloseTo(before + 7, 6);
  });

  it("connected_key without a wallet: no flow, the HL app instructions", async () => {
    const { s } = await act({ ...deps("hl_app", "acc_api", ""), provider: null }, { kind: "withdraw", amount_usd: 5 });
    expect(s.error?.kind).toBe("no_wallet");
    expect(s.error?.message).toMatch(/app.hyperliquid.xyz/);
  });

  it("unified account: the move is refused", async () => {
    expect((await demoAccounts.fundingInfo("acc_api")).limits?.unified).toBe(true);
    await expect(demoAccounts.prepareAction("acc_api", { kind: "usd_class_transfer", amount_usd: 1, to_perp: true })).rejects.toThrow(/unified/);
  });
});
