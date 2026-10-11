import { describe, expect, it, vi } from "vitest";
import { privateKeyToAccount } from "viem/accounts";
import type { Eip1193Provider } from "./eip1193";
import { initialSign, phaseOf, runSignFlow, signReducer, type SignDeps, type SignEvent, type SignState } from "./signFlow";
import type { AgentApprovalPrepareResponse, TradingAccount } from "./types";
import { ApiError } from "@/lib/api/client";

const MAIN = "0x1111111111111111111111111111111111111111";
const OTHER = "0x2222222222222222222222222222222222222222";
const KEY = `0x${"ab".repeat(32)}` as const;
const SIG = `0x${"cd".repeat(65)}`;
// Key order and odd values on purpose: the wallet must get these exact bytes.
const TYPED = {
  primaryType: "HyperliquidTransaction:ApproveAgent",
  domain: { name: "HyperliquidSignTransaction", version: "1", chainId: 42161, verifyingContract: "0x0000000000000000000000000000000000000000" },
  types: { "HyperliquidTransaction:ApproveAgent": [{ name: "hyperliquidChain", type: "string" }] },
  message: { hyperliquidChain: "Mainnet", nonce: 1700000000000, agentName: "copycat", extra: { z: 1, a: [3, 2, 1] } },
};
const PREPARED: AgentApprovalPrepareResponse = { typed_data: TYPED, action: { type: "approveAgent" }, nonce: 1700000000000 };
const ACCOUNT = { id: "acc_1", label: "Main", kind: "connected_signed", address: MAIN, agent_status: "active", active: false, created_ms: 1, has_main_key: false } as TradingAccount;

type Handler = (params: unknown) => unknown;
function provider(overrides: Record<string, Handler> = {}, chain = { id: 42161 }) {
  const calls: { method: string; params?: unknown }[] = [];
  const base: Record<string, Handler> = {
    eth_requestAccounts: () => [MAIN],
    eth_chainId: () => `0x${chain.id.toString(16)}`,
    wallet_switchEthereumChain: (p) => {
      chain.id = Number.parseInt((p as [{ chainId: string }])[0].chainId, 16);
      return null;
    },
    eth_signTypedData_v4: () => SIG,
  };
  const p: Eip1193Provider = {
    request: async ({ method, params }) => {
      calls.push({ method, params });
      const h = overrides[method] ?? base[method];
      if (!h) throw new Error(`unexpected ${method}`);
      return h(params);
    },
  };
  return { p, calls, chain };
}

function rpcError(code: number, message = "err") {
  return Object.assign(new Error(message), { code });
}

async function run(deps: Partial<SignDeps> & Pick<SignDeps, "provider">) {
  let state: SignState = initialSign;
  const steps: string[] = [];
  const dispatch = (e: SignEvent) => {
    state = signReducer(state, e);
    steps.push(state.step);
  };
  const prepare = vi.fn(async () => structuredClone(PREPARED));
  const submit = vi.fn(async () => ACCOUNT);
  const result = await runSignFlow({ label: "Main", prepare, submit, newAgentKey: () => KEY, ...deps }, dispatch);
  return { state, steps, prepare, submit, result };
}

describe("runSignFlow", () => {
  it("connects, prepares with the browser-made agent address, signs, submits", async () => {
    const { p, calls } = provider();
    const { state, steps, prepare, submit, result } = await run({ provider: p });
    expect(result).toEqual(ACCOUNT);
    expect(steps).toEqual(["connecting", "preparing", "signing", "submitting", "done"]);
    expect(phaseOf(state)).toBe("done");
    expect(prepare).toHaveBeenCalledWith({ main_address: MAIN, agent_address: privateKeyToAccount(KEY).address, agent_name: "copycat" });
    expect(submit).toHaveBeenCalledWith({ label: "Main", main_address: MAIN, agent_private_key: KEY, action: PREPARED.action, nonce: PREPARED.nonce, signature: SIG });
    expect(calls.map((c) => c.method)).not.toContain("wallet_switchEthereumChain");
  });

  it("passes typed_data to the wallet unmodified", async () => {
    const { p, calls } = provider();
    await run({ provider: p });
    const sign = calls.find((c) => c.method === "eth_signTypedData_v4");
    const [addr, payload] = sign?.params as [string, string];
    expect(addr).toBe(MAIN);
    expect(payload).toBe(JSON.stringify(TYPED));
    expect(JSON.parse(payload)).toStrictEqual(TYPED);
  });

  it("never puts the agent key in state", async () => {
    const { p } = provider();
    const { state } = await run({ provider: p });
    expect(JSON.stringify(state)).not.toContain(KEY.slice(2));
  });

  it("reports a rejected signature in the approve step and submits nothing", async () => {
    const { p } = provider({ eth_signTypedData_v4: () => { throw rpcError(4001); } });
    const { state, submit, result } = await run({ provider: p });
    expect(result).toBeNull();
    expect(state.error).toMatchObject({ kind: "rejected", phase: "approve" });
    expect(state.error?.message).toMatch(/rejected the signature/);
    expect(submit).not.toHaveBeenCalled();
  });

  it("reports a rejected connection in the connect step", async () => {
    const { p } = provider({ eth_requestAccounts: () => { throw rpcError(4001); } });
    const { state, prepare } = await run({ provider: p });
    expect(state.error).toMatchObject({ kind: "rejected", phase: "connect" });
    expect(state.error?.message).toMatch(/connection request/);
    expect(prepare).not.toHaveBeenCalled();
  });

  it("refuses the wrong account when refreshing a known one", async () => {
    const { p } = provider({ eth_requestAccounts: () => [OTHER] });
    const { state, prepare } = await run({ provider: p, expectedAddress: MAIN });
    expect(state.error).toMatchObject({ kind: "wrong_account", phase: "connect" });
    expect(prepare).not.toHaveBeenCalled();
  });

  it("uses the expected account when the wallet shares several", async () => {
    const { p } = provider({ eth_requestAccounts: () => [OTHER, MAIN] });
    const { prepare, state } = await run({ provider: p, expectedAddress: MAIN.toUpperCase().replace("0X", "0x") });
    expect(state.step).toBe("done");
    expect((prepare.mock.calls[0] as unknown[])[0]).toMatchObject({ main_address: MAIN });
  });

  it("switches the wallet to the domain's chain before signing", async () => {
    const { p, calls, chain } = provider({}, { id: 1 });
    const { steps, state } = await run({ provider: p });
    expect(steps).toEqual(["connecting", "preparing", "switching", "signing", "submitting", "done"]);
    expect(state.targetChain).toBe(42161);
    expect(chain.id).toBe(42161);
    const order = calls.map((c) => c.method);
    expect(order.indexOf("wallet_switchEthereumChain")).toBeLessThan(order.indexOf("eth_signTypedData_v4"));
  });

  it("adds the chain when the wallet does not know it (4902)", async () => {
    const chain = { id: 1 };
    const { p, calls } = provider({
      wallet_switchEthereumChain: () => { throw rpcError(4902); },
      wallet_addEthereumChain: () => { chain.id = 42161; return null; },
    }, chain);
    const { state } = await run({ provider: p });
    expect(state.step).toBe("done");
    expect(calls.map((c) => c.method)).toContain("wallet_addEthereumChain");
  });

  it("fails clearly when the user rejects the chain switch", async () => {
    const { p } = provider({ wallet_switchEthereumChain: () => { throw rpcError(4001); } }, { id: 1 });
    const { state, submit } = await run({ provider: p });
    expect(state.error).toMatchObject({ kind: "rejected", phase: "approve" });
    expect(state.error?.message).toMatch(/network switch/);
    expect(submit).not.toHaveBeenCalled();
  });

  it("says so when no wallet is installed", async () => {
    const { state, steps } = await run({ provider: null });
    expect(steps).toEqual(["error"]);
    expect(state.error).toMatchObject({ kind: "no_wallet", phase: "connect" });
  });

  it("calls an old api 'api too old'", async () => {
    const { p } = provider();
    const { state } = await run({ provider: p, prepare: async () => { throw new ApiError(404, "Not Found"); } });
    expect(state.error?.kind).toBe("api");
    expect(state.error?.message).toMatch(/^api too old/);
  });

  it("rejects a malformed signature before submitting", async () => {
    const { p } = provider({ eth_signTypedData_v4: () => "0xdead" });
    const { state, submit } = await run({ provider: p });
    expect(state.step).toBe("error");
    expect(submit).not.toHaveBeenCalled();
  });

  it("reset returns to idle", () => {
    expect(signReducer({ ...initialSign, step: "error" }, { type: "reset" })).toEqual(initialSign);
  });
});

describe("signSteps", () => {
  it("maps each state to the two visible steps", async () => {
    const { signSteps } = await import("./signView");
    const st = (s: Partial<SignState>) => signSteps({ ...initialSign, ...s }).map((x) => x.state);
    expect(st({})).toEqual(["todo", "todo"]);
    expect(st({ step: "connecting" })).toEqual(["doing", "todo"]);
    expect(st({ step: "switching", address: MAIN, targetChain: 42161 })).toEqual(["done", "doing"]);
    expect(signSteps({ ...initialSign, step: "switching", address: MAIN, targetChain: 42161 })[1].detail).toMatch(/Arbitrum One/);
    expect(st({ step: "error", error: { kind: "rejected", message: "no", phase: "approve" }, address: MAIN })).toEqual(["done", "failed"]);
    expect(st({ step: "error", error: { kind: "no_wallet", message: "no", phase: "connect" } })).toEqual(["failed", "todo"]);
    expect(st({ step: "done", address: MAIN })).toEqual(["done", "done"]);
  });
});

describe("chain from the backend's hex domain.chainId", () => {
  const withChain = (chainId: string) => async () => ({ ...structuredClone(PREPARED), typed_data: { ...TYPED, domain: { ...TYPED.domain, chainId } } });

  it("mainnet 0xa4b1: switches to Arbitrum One, then signs", async () => {
    const { p, calls, chain } = provider({}, { id: 1 });
    const { state } = await run({ provider: p, prepare: withChain("0xa4b1") });
    expect(state.step).toBe("done");
    expect(chain.id).toBe(42161);
    const sw = calls.find((c) => c.method === "wallet_switchEthereumChain");
    expect(sw?.params).toEqual([{ chainId: "0xa4b1" }]);
  });

  it("testnet 0x66eee: switches to Arbitrum Sepolia, adding it when unknown", async () => {
    const chain = { id: 42161 };
    const { p, calls } = provider({
      wallet_switchEthereumChain: () => { throw rpcError(4902); },
      wallet_addEthereumChain: (params) => {
        chain.id = Number.parseInt((params as [{ chainId: string }])[0].chainId, 16);
        return null;
      },
    }, chain);
    const { state, steps } = await run({ provider: p, prepare: withChain("0x66eee") });
    expect(state.step).toBe("done");
    expect(steps).toContain("switching");
    const add = calls.find((c) => c.method === "wallet_addEthereumChain")?.params as [{ chainId: string; chainName: string }];
    expect(add[0]).toMatchObject({ chainId: "0x66eee", chainName: "Arbitrum Sepolia" });
    expect(chain.id).toBe(421614);
  });

  it("already on the domain's chain: no switch prompt", async () => {
    const { p, calls } = provider({}, { id: 42161 });
    await run({ provider: p, prepare: withChain("0xa4b1") });
    expect(calls.map((c) => c.method)).not.toContain("wallet_switchEthereumChain");
  });

  it("a wallet that ignores the switch fails clearly before signing", async () => {
    const { p, calls } = provider({ wallet_switchEthereumChain: () => null }, { id: 1 });
    const { state } = await run({ provider: p, prepare: withChain("0xa4b1") });
    expect(state.error).toMatchObject({ kind: "chain", phase: "approve" });
    expect(state.error?.message).toMatch(/Arbitrum One/);
    expect(calls.map((c) => c.method)).not.toContain("eth_signTypedData_v4");
  });
});
