/**
 * End to end against the demo store + fake wallet: the same code path the
 * UI runs, with real EIP-712 signatures, so the typed data, the agent key
 * and the signature are checked for real, not mocked.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { demoAccounts, resetDemoAccounts } from "./demo";
import { DEMO_WALLET_ADDRESS, fakeWalletProvider } from "./demoWallet";
import { initialSign, runSignFlow, signReducer, type SignState } from "./signFlow";

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, advanceTimeDelta: 50 });
  resetDemoAccounts();
});

async function sign(mode: Parameters<typeof fakeWalletProvider>[0], expectedAddress?: string) {
  let s: SignState = initialSign;
  const result = await runSignFlow(
    { provider: fakeWalletProvider(mode, 0), label: "Rabby", expectedAddress, prepare: demoAccounts.prepare, submit: demoAccounts.submit },
    (e) => { s = signReducer(s, e); },
  );
  return { s, result };
}

describe("demo sign flow", () => {
  it("connects the demo wallet: real signature, verified, account added", async () => {
    const before = (await demoAccounts.list()).length;
    const { s, result } = await sign("approve");
    expect(s.step).toBe("done");
    expect(result?.address).toBe(DEMO_WALLET_ADDRESS);
    expect(result?.kind).toBe("connected_signed");
    expect(result?.agent_status).toBe("active");
    expect((await demoAccounts.list()).length).toBe(before + 1);
  });

  it("refreshing the same wallet updates it instead of duplicating", async () => {
    await sign("approve");
    const n = (await demoAccounts.list()).length;
    const { s } = await sign("approve", DEMO_WALLET_ADDRESS);
    expect(s.step).toBe("done");
    expect((await demoAccounts.list()).length).toBe(n);
  });

  it("a tampered signature is refused by the store", async () => {
    const prepared = await demoAccounts.prepare({ main_address: DEMO_WALLET_ADDRESS, agent_address: "0x1111111111111111111111111111111111111111" });
    await expect(
      demoAccounts.submit({ label: "x", main_address: DEMO_WALLET_ADDRESS, agent_private_key: `0x${"11".repeat(32)}`, action: prepared.action, nonce: prepared.nonce, signature: `0x${"ab".repeat(65)}` }),
    ).rejects.toThrow();
  });

  it("wrong account and rejection never touch the store", async () => {
    const n = (await demoAccounts.list()).length;
    expect((await sign("wrong_account", DEMO_WALLET_ADDRESS)).s.error?.kind).toBe("wrong_account");
    expect((await sign("reject_sign")).s.error?.kind).toBe("rejected");
    expect((await demoAccounts.list()).length).toBe(n);
  });
});

describe("demo store", () => {
  it("creates an unfunded wallet whose key derives its address", async () => {
    const { privateKeyToAccount } = await import("viem/accounts");
    const res = await demoAccounts.create({ label: "New", passphrase: "x".repeat(12) });
    expect(privateKeyToAccount(res.private_key as `0x${string}`).address.toLowerCase()).toBe(res.account.address);
    expect(res.account.agent_status).toBe("missing");
    const summary = await demoAccounts.summary(res.account.id);
    expect(summary.balances.total_usd).toBe(0);
    // the list never carries the key
    expect(JSON.stringify(await demoAccounts.list())).not.toContain(res.private_key.slice(2));
  });

  it("activate is exclusive; import-env only on an empty list", async () => {
    await demoAccounts.activate("acc_api");
    expect((await demoAccounts.list()).filter((a) => a.active).map((a) => a.id)).toEqual(["acc_api"]);
    await expect(demoAccounts.importEnv()).rejects.toThrow(/empty list/);
    resetDemoAccounts(true);
    expect((await demoAccounts.importEnv())[0].active).toBe(true);
  });
});
